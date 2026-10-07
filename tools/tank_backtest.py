#!/usr/bin/env python3
"""Backtest des Tank-Assistenten.

Spielt die gespeicherte Preishistorie (data/tank_assistent.json der AppDaemon-App) oder
synthetische Daten Stunde für Stunde ab und vergleicht Strategien:

  assistent   – die Optimierung des Tank-Assistenten (nur Wissen bis zum jeweiligen Zeitpunkt)
  reserve     – tanken, sobald die Reserve naht, zur zufälligen Tageszeit an zufälliger Tankstelle
  morgens     – tanken bei < 25 % um 7 Uhr an der günstigsten Tankstelle

Kennzahl: Ersparnis gegenüber dem Durchschnittspreis (wie in der App).

Aufruf:
  python3 tools/tank_backtest.py --synthetisch 90
  python3 tools/tank_backtest.py --zustand /addon_configs/a0d7b954_appdaemon/apps/tank_assistent/data/tank_assistent.json
  Optionen: --km "mo=15,di=15,mi=15,do=200,fr=15,sa=25,so=10" --l100 8.5 --tank 58 --reserve 100
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "appdaemon", "apps", "tank_assistent"))
sys.path.insert(0, os.path.join(HERE, "..", "tests", "tank_assistent"))

from ta_calendar import Calendar  # noqa: E402
from ta_model import TZ, Discounts, DiscountRule, PriceHistory, PriceModel, from_hour_key  # noqa: E402
from ta_optimizer import StationInfo, build_slots, optimize  # noqa: E402

DAYS = ["mo", "di", "mi", "do", "fr", "sa", "so"]


def parse_km(text: str) -> dict[int, float]:
    out = {}
    for part in text.split(","):
        key, value = part.split("=")
        out[DAYS.index(key.strip().lower())] = float(value)
    return out


def run(history: PriceHistory, brands: dict, km: dict, l100: float, cap: float, reserve_km: float,
        discounts: Discounts, warmup: int = 14, hours=(6, 22), seed: int = 7) -> dict:
    cal = Calendar()
    keys = sorted({k for h in history.data.values() for k in h})
    start = from_hour_key(keys[0]) + timedelta(days=warmup)
    end = from_hour_key(keys[-1])
    stations = history.stations()
    reserve_l = reserve_km * l100 / 100
    rng = random.Random(seed)

    def km_for(day):
        typ = cal.day_type(day)
        return km.get(typ, 15.0) if (typ != 3 or cal.is_workday(day)) else km.get(6, 10.0)

    def eff(st, t):
        p = history.price_at(st, t)
        return None if p is None else p - discounts.euro(brands.get(st), t.date())

    results = {}
    for name in ("assistent", "reserve", "morgens"):
        fuel = cap * 0.6
        t = start.replace(hour=0)
        paid, liters_total = 0.0, 0.0
        avg_sum, avg_n = 0.0, 0
        model = None
        planned_random_hour = None
        while t < end:
            if t.hour == 0:
                fuel -= km_for(t.date()) * l100 / 100        # Tagesverbrauch
                planned_random_hour = rng.randint(hours[0], hours[1] - 1)
            if hours[0] <= t.hour < hours[1]:
                prices = {s: eff(s, t) for s in stations}
                prices = {s: p for s, p in prices.items() if p is not None}
                for s in stations:
                    raw = history.price_at(s, t)
                    if raw is not None:
                        avg_sum, avg_n = avg_sum + raw, avg_n + 1
                if prices:
                    buy = None
                    if name == "assistent":
                        if model is None or t.hour == hours[0]:
                            past = PriceHistory({s: {k: v for k, v in h.items() if k < int(t.timestamp() // 3600)}
                                                 for s, h in history.data.items()})
                            model = PriceModel.fit(past, cal, t)
                        current = {s: history.price_at(s, t) for s in prices}
                        infos = [StationInfo(s, s, brands.get(s, ""), discounts.euro(brands.get(s), t.date()),
                                             current[s], True) for s in prices]
                        fc = model.forecaster(cal, t, current)
                        slots, tl = build_slots(t, fuel, cap, 0.0, km_for, l100, infos, fc,
                                                lambda s, x: True, lambda st, d: discounts.euro(st.brand, d),
                                                hours, 10)
                        plan = optimize(t, slots, tl, fuel, reserve_l)
                        if plan.now_ok or fuel < reserve_l:
                            buy = min(prices, key=prices.get)
                    elif name == "reserve":
                        need = fuel - km_for(t.date() + timedelta(days=1)) * l100 / 100 < reserve_l
                        if (need and t.hour == planned_random_hour) or fuel < reserve_l:
                            buy = rng.choice(list(prices))
                    elif name == "morgens":
                        if (fuel < cap * 0.25 and t.hour == 7) or fuel < reserve_l:
                            buy = min(prices, key=prices.get)
                    if buy:
                        liters = cap - fuel
                        paid += liters * prices[buy]
                        liters_total += liters
                        fuel = cap
            t += timedelta(hours=1)
        baseline = avg_sum / avg_n if avg_n else 0
        avg_paid = paid / liters_total if liters_total else 0
        results[name] = {
            "liter": round(liters_total, 1),
            "preis_bezahlt": round(avg_paid, 4),
            "durchschnitt": round(baseline, 4),
            "ersparnis_eur": round(liters_total * (baseline - avg_paid), 2),
            "ersparnis_ct_l": round((baseline - avg_paid) * 100, 2),
        }
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zustand", help="Pfad zu tank_assistent.json")
    ap.add_argument("--synthetisch", type=int, help="Tage synthetischer Daten")
    ap.add_argument("--km", default="mo=15,di=15,mi=15,do=200,fr=15,sa=25,so=10")
    ap.add_argument("--l100", type=float, default=8.5)
    ap.add_argument("--tank", type=float, default=58)
    ap.add_argument("--reserve", type=float, default=100)
    args = ap.parse_args()

    discounts = Discounts([DiscountRule("ESSO", 1), DiscountRule("AGIP", 1)])
    if args.synthetisch:
        from datetime import datetime

        from synth import STATIONS, generate
        start = datetime(2026, 4, 1, tzinfo=TZ)
        history = generate(start, args.synthetisch, seed=3)
        brands = {s: b for s, (b, _o) in STATIONS.items()}
    elif args.zustand:
        with open(args.zustand, encoding="utf-8") as fh:
            data = json.load(fh)
        history = PriceHistory(data["history"])
        brands = {s: s.split(".", 1)[1].split("_")[0].upper() for s in history.stations()}
    else:
        ap.error("--zustand oder --synthetisch angeben")
    res = run(history, brands, parse_km(args.km), args.l100, args.tank, args.reserve, discounts)
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

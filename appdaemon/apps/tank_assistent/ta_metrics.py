"""Tankerkennung und ehrliche Ersparnis-Kennzahlen.

Hauptkennzahl: Ersparnis gegenüber dem Durchschnittspreis aller Tankstellen über alle
Stunden im Verfügbarkeitszeitraum seit dem letzten Tanken (das hätte ein Durchschnitts-
fahrer in der Gegend im selben Zeitraum gezahlt).

    ersparnis = liter × (durchschnitt − eigener Effektivpreis)
              = zeitpunkt + tankstellenwahl + rabatt

Ausschöpfung: Anteil der im Nachhinein bestmöglichen Ersparnis (günstigster
Effektivpreis zwischen den beiden Tankvorgängen).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from ta_model import TZ, Discounts, PriceHistory, from_hour_key, hour_key

REFUEL_THRESHOLD_PCT = 15.0


@dataclass
class Refuel:
    time: str            # ISO
    liters: float
    station: str
    station_name: str
    price_raw: float
    discount: float
    price_eff: float
    baseline: float | None
    station_avg: float | None
    best_possible: float | None
    saving_total: float | None
    saving_timing: float | None
    saving_station: float | None
    saving_discount: float
    possible: float | None
    exploitation: float | None   # 0..1
    source: str                  # "bestaetigt" | "geschaetzt"

    def to_dict(self) -> dict:
        return asdict(self)


class RefuelDetector:
    """Erkennt Tankvorgänge an einem deutlichen Anstieg des Tankstands (%)."""

    def __init__(self, last_pct: float | None = None, threshold: float = REFUEL_THRESHOLD_PCT):
        self.last_pct = last_pct
        self.threshold = threshold

    def update(self, pct: float) -> float | None:
        """Gibt den Anstieg in Prozentpunkten zurück, wenn getankt wurde."""
        previous, self.last_pct = self.last_pct, pct
        if previous is not None and pct - previous >= self.threshold:
            return pct - previous
        return None


def _station_hours(history: PriceHistory, station: str, start: datetime, end: datetime,
                   hours: tuple[int, int]) -> list[tuple[datetime, float]]:
    lo, hi = hour_key(start), hour_key(end)
    result = []
    for key, price in history.data.get(station, {}).items():
        if lo <= key <= hi:
            dt = from_hour_key(key)
            if hours[0] <= dt.hour < hours[1]:
                result.append((dt, price))
    return result


def evaluate_refuel(
    *,
    history: PriceHistory,
    discounts: Discounts,
    brands: dict[str, str],
    names: dict[str, str],
    station: str,
    when: datetime,
    liters: float,
    since: datetime | None,
    hours: tuple[int, int] = (6, 22),
    source: str = "geschaetzt",
) -> Refuel:
    when = when.astimezone(TZ)
    since = (since or when - timedelta(days=14)).astimezone(TZ)
    price_raw = history.price_at(station, when)
    if price_raw is None:
        price_raw = 0.0
    disc = discounts.euro(brands.get(station), when.date())
    price_eff = price_raw - disc

    all_raw: list[float] = []
    best_eff = None
    station_raw: list[float] = []
    for st in history.stations():
        for dt, price in _station_hours(history, st, since, when, hours):
            all_raw.append(price)
            eff = price - discounts.euro(brands.get(st), dt.date())
            best_eff = eff if best_eff is None else min(best_eff, eff)
            if st == station:
                station_raw.append(price)

    baseline = sum(all_raw) / len(all_raw) if all_raw else None
    station_avg = sum(station_raw) / len(station_raw) if station_raw else None
    saving_discount = liters * disc
    saving_total = saving_timing = saving_station = possible = exploitation = None
    if baseline is not None and price_raw:
        saving_total = liters * (baseline - price_eff)
        if station_avg is not None:
            saving_timing = liters * (station_avg - price_raw)
            saving_station = liters * (baseline - station_avg)
        if best_eff is not None:
            possible = liters * (baseline - best_eff)
            if possible > 0.01:
                exploitation = max(0.0, min(1.0, saving_total / possible))

    return Refuel(
        time=when.isoformat(), liters=round(liters, 1), station=station,
        station_name=names.get(station, station), price_raw=round(price_raw, 3),
        discount=round(disc, 3), price_eff=round(price_eff, 3),
        baseline=_r(baseline, 3), station_avg=_r(station_avg, 3), best_possible=_r(best_eff, 3),
        saving_total=_r(saving_total, 2), saving_timing=_r(saving_timing, 2),
        saving_station=_r(saving_station, 2), saving_discount=round(saving_discount, 2),
        possible=_r(possible, 2), exploitation=_r(exploitation, 3), source=source,
    )


def aggregate(refuels: list[dict], now: datetime) -> dict:
    """Summen für Monat, Jahr und gesamt."""
    now = now.astimezone(TZ)
    out = {}
    for label, pred in (
        ("monat", lambda d: d.year == now.year and d.month == now.month),
        ("jahr", lambda d: d.year == now.year),
        ("gesamt", lambda d: True),
    ):
        items = [r for r in refuels if pred(datetime.fromisoformat(r["time"]).astimezone(TZ))]
        total = sum(r["saving_total"] or 0.0 for r in items)
        possible = sum(r["possible"] or 0.0 for r in items if r["possible"])
        out[label] = {
            "tankvorgaenge": len(items),
            "liter": round(sum(r["liters"] for r in items), 1),
            "ersparnis": round(total, 2),
            "zeitpunkt": round(sum(r["saving_timing"] or 0.0 for r in items), 2),
            "tankstelle": round(sum(r["saving_station"] or 0.0 for r in items), 2),
            "rabatt": round(sum(r["saving_discount"] or 0.0 for r in items), 2),
            "ausschoepfung": round(total / possible, 3) if possible > 0.01 else None,
        }
    return out


def _r(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)

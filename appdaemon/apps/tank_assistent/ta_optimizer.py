"""Tankplanung als optimales Stoppproblem.

Idee: Bis der Tank die Reserve erreicht, ist jede Stunde (im Verfügbarkeitszeitraum,
bei geöffneter Tankstelle) ein möglicher Tankzeitpunkt. Getankt wird immer voll.

Vergleich auf gleicher Strecke: Liter, die ich jetzt nicht tanke, kaufe ich später zum
dann gültigen Preis. Nach etwas Umformen hängen die Kosten eines Tankzeitpunkts k nur von

    kosten_k = liter_k × (preis_k − P_lr)

ab, wobei P_lr der langfristig zu erwartende Preis ist (Mittel der erwarteten Preise im
Horizont). Ist der Preis unter P_lr, lohnt es sich, möglichst viele Liter zu kaufen, also
eher später (größerer freier Platz); ist er darüber, eher früh und wenig.

Rückwärtsrechnung (dynamische Programmierung) mit Normalverteilung der Preise:
    V_k = E[min(kosten_k(p), V_{k+1})]
Reservationspreis r_k: tanken, wenn preis_k ≤ r_k = P_lr + V_{k+1} / liter_k.
Bis zum nächsten 12-Uhr-Sprung ist der aktuelle Preis eine garantierte Obergrenze
(Erhöhungen sind nur um 12 Uhr erlaubt), daher dort Unsicherheit 0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Callable

from ta_model import TZ, Forecast, pricing_day_start

INF = float("inf")


@dataclass
class StationInfo:
    station_id: str
    name: str
    brand: str
    discount_eur: float          # Rabatt heute (€/l)
    current_raw: float | None    # aktueller Rohpreis
    open_now: bool | None        # Live-Status (None = unbekannt)


@dataclass
class Slot:
    start: datetime
    station: str
    mu: float          # erwarteter Effektivpreis
    sigma: float
    fuel_before: float
    liters: float
    reservation: float = INF
    stop_probability: float = 0.0
    value_after: float = 0.0


@dataclass
class Plan:
    status: str                       # muss | jetzt | heute | warten | unbekannt
    created: datetime
    fuel_l: float
    reserve_l: float
    p_lr: float | None = None
    now_ok: bool = False
    now_station: str | None = None
    now_price: float | None = None
    now_advantage_eur: float = 0.0
    best: Slot | None = None
    latest: datetime | None = None
    reserve_at: datetime | None = None
    truncated: bool = False
    expected_value_eur: float = 0.0
    guaranteed_until: datetime | None = None
    slots: list[Slot] = field(default_factory=list)


def _phi(z: float) -> float:
    return math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)


def _cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def expected_min(m: float, s: float, v: float) -> float:
    """E[min(X, v)] für X ~ N(m, s²)."""
    if v == INF:
        return m
    if s <= 1e-9:
        return min(m, v)
    z = (v - m) / s
    return m * _cdf(z) - s * _phi(z) + v * (1 - _cdf(z))


def build_slots(
    now: datetime,
    fuel_l: float,
    capacity_l: float,
    km_remaining_today: float,
    km_for_day: Callable[[date], float],
    l100: float,
    stations: list[StationInfo],
    forecast: Callable[[str, datetime], Forecast | None],
    is_open: Callable[[str, datetime], bool],
    discount_for: Callable[[StationInfo, date], float],
    hours: tuple[int, int] = (6, 22),
    horizon_days: int = 10,
    windows_for_day: Callable[[date], list[tuple[int, int]]] | None = None,
) -> tuple[list[Slot], list[tuple[datetime, float]]]:
    """Mögliche Tankzeitpunkte und Tankstand-Verlauf (konservativ: Tagesverbrauch morgens)."""
    now = now.astimezone(TZ)
    today = now.date()
    level = fuel_l - km_remaining_today * l100 / 100.0
    timeline = [(now, level)]
    slots: list[Slot] = []
    for offset in range(horizon_days + 1):
        day = today + timedelta(days=offset)
        if offset > 0:
            level -= km_for_day(day) * l100 / 100.0
            timeline.append((datetime.combine(day, time(0), TZ), level))
        windows = windows_for_day(day) if windows_for_day else [hours]
        day_hours = sorted({h for a, b in windows for h in range(max(a, hours[0]), min(b, hours[1]))})
        for hour in day_hours:
            t = datetime.combine(day, time(hour), TZ)
            if t + timedelta(hours=1) <= now:
                continue
            current_slot = t <= now
            t_eff = now if current_slot else t
            best = None
            for st in stations:
                if current_slot:
                    if st.open_now is False or st.current_raw is None:
                        continue
                    mu, sigma = st.current_raw - st.discount_eur, 0.0
                else:
                    if not is_open(st.station_id, t_eff):
                        continue
                    fc = forecast(st.station_id, t_eff)
                    if fc is None:
                        continue
                    mu = fc.mu if fc.upper is None else min(fc.mu, fc.upper)
                    mu -= discount_for(st, day)
                    sigma = fc.sigma
                if best is None or mu < best[1]:
                    best = (st.station_id, mu, sigma)
            if best is None:
                continue
            slots.append(Slot(t_eff, best[0], best[1], best[2], level, max(0.0, capacity_l - level)))
    return slots, timeline


def optimize(
    now: datetime,
    slots: list[Slot],
    timeline: list[tuple[datetime, float]],
    fuel_l: float,
    reserve_l: float,
    min_advantage_eur: float = 0.0,
    min_liters: float = 10.0,
) -> Plan:
    now = now.astimezone(TZ)
    plan = Plan(status="unbekannt", created=now, fuel_l=fuel_l, reserve_l=reserve_l)
    if not slots:
        return plan

    # Zeitpunkt, an dem die Reserve erreicht wird (ohne Tanken)
    for t, level in timeline:
        if level < reserve_l:
            plan.reserve_at = t
            break

    below_now = fuel_l < reserve_l
    feasible = [s for s in slots if s.fuel_before >= reserve_l]
    if below_now or not feasible:
        feasible = slots[:1]            # sofort bzw. nächstmöglich tanken
        truncated = False
    else:
        truncated = plan.reserve_at is None
    plan.truncated = truncated
    plan.latest = feasible[-1].start

    # Langfristiger Preis: was künftiger Kraftstoff bei geschicktem Tanken typischerweise
    # kostet – Mittel der günstigsten erwarteten Stunde je Tag im Horizont.
    daily_min: dict = {}
    for s in slots:
        daily_min[s.start.date()] = min(s.mu, daily_min.get(s.start.date(), s.mu))
    p_lr = sum(daily_min.values()) / len(daily_min)
    plan.p_lr = p_lr

    # Rückwärtsrechnung
    value_next = 0.0 if truncated else INF
    for idx, slot in enumerate(reversed(feasible)):
        slot.value_after = value_next
        if slot.liters < min_liters and not (idx == 0 and value_next == INF):
            slot.reservation = -INF          # lohnt nicht (zu wenig Platz im Tank)
            continue
        m = slot.liters * (slot.mu - p_lr)
        s = slot.liters * slot.sigma
        if value_next == INF:
            slot.reservation = INF
        elif slot.liters > 0:
            slot.reservation = p_lr + value_next / slot.liters
        value_next = expected_min(m, s, value_next)
    plan.expected_value_eur = -value_next

    # Vorwärts: Wahrscheinlichkeit, in welchem Slot getankt wird
    survive = 1.0
    for slot in feasible:
        if slot.reservation == INF:
            q = 1.0
        elif slot.reservation == -INF:
            q = 0.0
        elif slot.sigma <= 1e-9:
            q = 1.0 if slot.mu <= slot.reservation else 0.0
        else:
            q = _cdf((slot.reservation - slot.mu) / slot.sigma)
        slot.stop_probability = survive * q
        survive *= 1 - q
    plan.slots = feasible
    candidates = [s for s in feasible if s.reservation != -INF]
    no_refuel_planned = not candidates or max(s.stop_probability for s in candidates) <= 1e-9
    if no_refuel_planned:
        # Im Horizont ist kein Tanken nötig/sinnvoll -> günstigster erwarteter Zeitpunkt als Richtwert
        plan.best = min(candidates or feasible, key=lambda s: (s.mu, s.start.timestamp()))
    else:
        plan.best = max(candidates, key=lambda s: (round(s.stop_probability, 6), -s.start.timestamp()))

    first = feasible[0]
    if first.start == now or first.start <= now:
        cost_now = first.liters * (first.mu - p_lr)
        plan.now_station = first.station
        plan.now_price = first.mu
        plan.now_ok = first.reservation != -INF and (
            first.value_after == INF or cost_now <= first.value_after)
        if first.value_after != INF:
            plan.now_advantage_eur = first.value_after - cost_now

    if plan.best and pricing_day_start(plan.best.start) == pricing_day_start(now):
        nxt = pricing_day_start(now) + timedelta(days=1)
        plan.guaranteed_until = nxt - timedelta(minutes=1)

    today = now.date()
    if below_now or plan.latest.date() == today:
        plan.status = "muss"
    elif plan.now_ok and plan.now_advantage_eur >= min_advantage_eur:
        plan.status = "jetzt"
    elif plan.best.start.date() == today and not no_refuel_planned:
        plan.status = "heute"
    else:
        plan.status = "warten"
    return plan

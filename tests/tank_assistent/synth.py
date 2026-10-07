"""Synthetische Preisdaten nach dem Muster der 12-Uhr-Regel (für Tests und Backtest)."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from ta_model import TZ, PriceHistory

STATIONS = {
    "sensor.esso_alpenstr_13_super": ("ESSO", 0.000),
    "sensor.agip_eni_putrichstrasse_29_super": ("AGIP ENI", 0.010),
    "sensor.jet_puetrichstr_22_super": ("JET", -0.015),
    "sensor.pinoil_alpenstrasse_5_super": ("Pinoil", -0.020),
}


def price_curve(base: float, hour_since_noon: int) -> float:
    """Sprung um 12 Uhr (+7 ct), danach Absenkung bis zum nächsten Mittag, Abenddelle."""
    decline = 0.07 * hour_since_noon / 23
    evening = 0.015 if 6 <= hour_since_noon <= 9 else 0.0   # 18–21 Uhr etwas günstiger
    return base + 0.07 - decline - evening


def generate(start: datetime, days: int, seed: int = 1, trend: float = 0.0) -> PriceHistory:
    rng = random.Random(seed)
    history = PriceHistory()
    base = 1.72
    t = start.astimezone(TZ).replace(minute=0, second=0, microsecond=0)
    end = t + timedelta(days=days)
    while t < end:
        if t.hour == 12:
            base += trend + rng.gauss(0, 0.01)
        hs = (t.hour - 12) % 24
        for station, (_brand, offset) in STATIONS.items():
            history.add(station, t, round(price_curve(base, hs) + offset + rng.gauss(0, 0.002), 3))
        t += timedelta(hours=1)
    return history


def at(y, m, d, h=0, mi=0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=TZ)

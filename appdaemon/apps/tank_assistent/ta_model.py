"""Lernende Modelle des Tank-Assistenten.

PriceHistory   stündliche Preise je Tankstelle (Minimum je Stunde)
PriceModel     Preisprofil nach Wochentag × Stunde, Trend, Feiertags-/Ferieneffekt,
               12-Uhr-Regel (Erhöhungen nur um 12 Uhr, Senkungen jederzeit)
OpeningModel   Öffnungswahrscheinlichkeit je Tankstelle, Tagestyp und Stunde
ConsumptionModel  km je Tagestyp und Verbrauch (l/100 km) aus der Historie
Discounts      Rabattregeln (z. B. ADAC bei ESSO/AGIP)

Alle Zeiten sind zeitzonenbewusst (Europe/Berlin). Kein AppDaemon-Import.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from ta_calendar import SUNDAY_TYPE, Calendar

TZ = ZoneInfo("Europe/Berlin")
PRICE_JUMP_HOUR = 12          # 12-Uhr-Regel
HISTORY_DAYS = 70
HALF_LIFE_DAYS = 21.0


# --------------------------------------------------------------------------- Zeit
def hour_key(dt: datetime) -> int:
    return int(dt.timestamp() // 3600)


def from_hour_key(key: int) -> datetime:
    return datetime.fromtimestamp(key * 3600, TZ)


def pricing_day_start(dt: datetime) -> datetime:
    """Beginn des „Preistags“: 12:00 Uhr (Preiserhöhungen sind nur um 12 Uhr erlaubt)."""
    local = dt.astimezone(TZ)
    day = local.date() if local.hour >= PRICE_JUMP_HOUR else local.date() - timedelta(days=1)
    return datetime.combine(day, time(PRICE_JUMP_HOUR), TZ)


def phase(dt: datetime) -> int:
    """Stunden seit dem letzten 12-Uhr-Sprung (0..23)."""
    delta = dt.astimezone(TZ) - pricing_day_start(dt)
    return max(0, min(23, int(delta.total_seconds() // 3600)))


def _weight(age_days: float, half_life: float = HALF_LIFE_DAYS) -> float:
    return 0.5 ** (max(0.0, age_days) / half_life)


# ------------------------------------------------------------------- Historie
class PriceHistory:
    """{station: {hour_key: preis}} – Rohpreise ohne Rabatt, letzter Wert je Stunde.

    Bewusst nicht das Minimum: Tankerkönig aktualisiert nur alle 30 Minuten, ein Wert
    kurz nach 12 Uhr zeigt oft noch den alten Preis vor dem 12-Uhr-Sprung."""

    def __init__(self, data: dict | None = None) -> None:
        self.data: dict[str, dict[int, float]] = {
            s: {int(k): float(v) for k, v in hours.items()} for s, hours in (data or {}).items()
        }

    def add(self, station: str, dt: datetime, price: float) -> None:
        hours = self.data.setdefault(station, {})
        key = hour_key(dt)
        hours[key] = price

    def prune(self, now: datetime, days: int = HISTORY_DAYS) -> None:
        limit = hour_key(now - timedelta(days=days))
        for hours in self.data.values():
            for key in [k for k in hours if k < limit]:
                del hours[key]

    def price_at(self, station: str, dt: datetime) -> float | None:
        """Preis zur Stunde dt (oder der letzte bekannte davor, max. 3 h zurück)."""
        hours = self.data.get(station, {})
        key = hour_key(dt)
        for back in range(4):
            if key - back in hours:
                return hours[key - back]
        return None

    def stations(self) -> list[str]:
        return list(self.data)

    def to_dict(self) -> dict:
        return {s: {str(k): v for k, v in hours.items()} for s, hours in self.data.items()}


# ------------------------------------------------------------------ Rabatte
@dataclass
class DiscountRule:
    brand: str
    cent: float
    ab: date | None = None
    bis: date | None = None

    @classmethod
    def from_config(cls, cfg: dict) -> "DiscountRule":
        def _d(value):
            return date.fromisoformat(str(value)) if value else None
        return cls(str(cfg["marke"]).upper(), float(cfg["cent"]), _d(cfg.get("ab")), _d(cfg.get("bis")))


class Discounts:
    def __init__(self, rules: list[DiscountRule] | None = None) -> None:
        self.rules = rules or []

    def cent(self, brand: str | None, day: date) -> float:
        brand_u = (brand or "").upper()
        best = 0.0
        for rule in self.rules:
            if rule.brand and rule.brand in brand_u:
                if (rule.ab is None or day >= rule.ab) and (rule.bis is None or day <= rule.bis):
                    best = max(best, rule.cent)
        return best

    def euro(self, brand: str | None, day: date) -> float:
        return self.cent(brand, day) / 100.0


# --------------------------------------------------------------- Preismodell
@dataclass
class Forecast:
    mu: float          # erwarteter Rohpreis
    sigma: float       # Unsicherheit (€/l)
    upper: float | None  # garantierte Obergrenze (bis zum nächsten 12-Uhr-Sprung)


@dataclass
class PriceModel:
    """Wird bei jeder Planung aus der Historie neu gerechnet (schnell, < 50 ms)."""

    shape: dict = field(default_factory=dict)       # (s, typ, phase) -> (mittel, n)
    shape_any: dict = field(default_factory=dict)   # (s, phase) -> (mittel, n)
    market_shape: dict = field(default_factory=dict)  # (typ, phase) -> (mittel, n)
    market_phase: dict = field(default_factory=dict)  # phase -> (mittel, n)
    offset: dict = field(default_factory=dict)      # s -> €/l gegenüber Markt
    market: dict = field(default_factory=dict)      # Preistag -> Marktniveau
    slope: float = 0.0                              # €/l pro Tag
    trend_short_long: float = 0.0                   # €/l (2 Tage gegen 14 Tage)
    sigma_day: float = 0.02
    sigma_shape: float = 0.01
    effects: dict = field(default_factory=dict)     # flag -> €/l
    days_of_data: int = 0
    damping: float = 0.8

    # ---------------------------------------------------------------- Lernen
    @classmethod
    def fit(cls, history: PriceHistory, calendar: Calendar, now: datetime) -> "PriceModel":
        model = cls()
        current_pd = pricing_day_start(now).date()
        # Preistage je Tankstelle (aktueller, unvollständiger Preistag ausgenommen)
        per_station: dict[str, dict[date, dict[int, float]]] = {}
        for station, hours in history.data.items():
            days: dict[date, dict[int, float]] = {}
            for key, price in hours.items():
                dt = from_hour_key(key)
                pd = pricing_day_start(dt).date()
                if pd >= current_pd:
                    continue
                days.setdefault(pd, {})[phase(dt)] = price
            per_station[station] = {pd: hrs for pd, hrs in days.items() if len(hrs) >= 12}
        pd_mean = {s: {pd: sum(h.values()) / len(h) for pd, h in days.items()}
                   for s, days in per_station.items()}
        all_pds = sorted({pd for days in pd_mean.values() for pd in days})
        model.days_of_data = len(all_pds)
        if not all_pds:
            return model

        # Marktniveau und Tankstellen-Offsets
        raw_market = {pd: _mean([m[pd] for m in pd_mean.values() if pd in m]) for pd in all_pds}
        for s, means in pd_mean.items():
            pairs = [(means[pd] - raw_market[pd], _weight((current_pd - pd).days)) for pd in means]
            model.offset[s] = _wmean(pairs) if pairs else 0.0
        model.market = {
            pd: _mean([m[pd] - model.offset.get(s, 0.0) for s, m in pd_mean.items() if pd in m])
            for pd in all_pds
        }

        # Tagesverlauf (Abweichung vom Preistag-Mittel)
        acc: dict = {}
        acc_any: dict = {}
        acc_mkt: dict = {}
        acc_ph: dict = {}
        for s, days in per_station.items():
            for pd, hrs in days.items():
                w = _weight((current_pd - pd).days)
                typ = calendar.day_type(pd)
                for ph, price in hrs.items():
                    dev = price - pd_mean[s][pd]
                    for store, key in ((acc, (s, typ, ph)), (acc_any, (s, ph)),
                                       (acc_mkt, (typ, ph)), (acc_ph, ph)):
                        a = store.setdefault(key, [0.0, 0.0, 0])
                        a[0] += w * dev
                        a[1] += w
                        a[2] += 1
        model.shape = {k: (a[0] / a[1], a[2]) for k, a in acc.items() if a[1] > 0}
        model.shape_any = {k: (a[0] / a[1], a[2]) for k, a in acc_any.items() if a[1] > 0}
        model.market_shape = {k: (a[0] / a[1], a[2]) for k, a in acc_mkt.items() if a[1] > 0}
        model.market_phase = {k: (a[0] / a[1], a[2]) for k, a in acc_ph.items() if a[1] > 0}

        residuals = []
        for s, days in per_station.items():
            for pd, hrs in days.items():
                typ = calendar.day_type(pd)
                for ph, price in hrs.items():
                    residuals.append(price - pd_mean[s][pd] - model.shape_value(s, typ, ph))
        if len(residuals) >= 24:
            model.sigma_shape = min(0.05, max(0.003, _std(residuals)))

        # Trend (Steigung der letzten 14 Preistage, gedämpft fortgeschrieben)
        series = [(pd, model.market[pd]) for pd in all_pds if (current_pd - pd).days <= 14]
        if len(series) >= 4:
            xs = [(pd - series[0][0]).days for pd, _ in series]
            ys = [v for _, v in series]
            model.slope = max(-0.03, min(0.03, _slope(xs, ys)))
        if series:
            short = [v for pd, v in series if (current_pd - pd).days <= 2]
            model.trend_short_long = (_mean(short) if short else series[-1][1]) - _mean([v for _, v in series])
        diffs = [model.market[b] - model.market[a] for a, b in zip(all_pds, all_pds[1:]) if (b - a).days == 1]
        if len(diffs) >= 5:
            model.sigma_day = min(0.06, max(0.005, _std(diffs[-30:])))

        # Feiertags- und Ferieneffekt (mit Schrumpfung gegen 0)
        flagged = {pd: calendar.flags(pd) for pd in all_pds}
        for flag in ("vor_feiertag", "ferienbeginn"):
            res = []
            for pd in all_pds:
                if flag not in flagged[pd]:
                    continue
                around = [model.market[o] for o in all_pds
                          if 0 < abs((o - pd).days) <= 3 and not flagged[o]]
                if around:
                    res.append(model.market[pd] - _mean(around))
            if res:
                model.effects[flag] = sum(res) / (len(res) + 5)
        return model

    # ------------------------------------------------------------- Abfragen
    def shape_value(self, station: str, typ: int, ph: int) -> float:
        value = self.shape.get((station, typ, ph))
        if value and value[1] >= 2:
            return value[0]
        value = self.shape_any.get((station, ph))
        if value and value[1] >= 3:
            return value[0]
        value = self.market_shape.get((typ, ph))
        if value and value[1] >= 2:
            return value[0]
        value = self.market_phase.get(ph)
        if value and value[1] >= 3:
            return value[0]
        return 0.0

    def trend_label(self) -> str:
        if self.trend_short_long > 0.01:
            return "steigend"
        if self.trend_short_long < -0.01:
            return "fallend"
        return "stabil"

    def cheapest_hours(self, calendar: Calendar, day: date) -> list[int]:
        """Typisch günstigste Uhrzeiten (Markt) für einen Kalendertag – für Texte."""
        scores = []
        for hour in range(24):
            dt = datetime.combine(day, time(hour), TZ)
            pd = pricing_day_start(dt).date()
            scores.append((self._market_shape(calendar.day_type(pd), phase(dt)), hour))
        return [h for _, h in sorted(scores)[:3]]

    def _market_shape(self, typ: int, ph: int) -> float:
        value = self.market_shape.get((typ, ph)) or self.market_phase.get(ph)
        return value[0] if value else 0.0

    def forecaster(
        self, calendar: Calendar, now: datetime, current: dict[str, float]
    ) -> Callable[[str, datetime], Forecast | None]:
        """Liefert f(tankstelle, zeitpunkt) -> Forecast (Rohpreis)."""
        now = now.astimezone(TZ)
        pd0 = pricing_day_start(now)
        typ0 = calendar.day_type(pd0.date())
        ph_now = phase(now)
        bases = [price - self.shape_value(s, typ0, ph_now) - self.offset.get(s, 0.0)
                 for s, price in current.items()]
        base0 = _mean(bases) if bases else None

        def forecast(station: str, dt: datetime) -> Forecast | None:
            cur = current.get(station)
            if cur is None or base0 is None:
                return None
            dt = dt.astimezone(TZ)
            pd = pricing_day_start(dt)
            j = (pd.date() - pd0.date()).days
            typ = calendar.day_type(pd.date())
            ph = phase(dt)
            if j <= 0:
                expected = cur + self.shape_value(station, typ0, ph) - self.shape_value(station, typ0, ph_now)
                return Forecast(min(cur, expected), 0.0, cur)
            trend = self.slope * sum(self.damping ** i for i in range(1, j + 1))
            effect = sum(self.effects.get(f, 0.0) for f in calendar.flags(pd.date()))
            mu = base0 + trend + effect + self.offset.get(station, 0.0) + self.shape_value(station, typ, ph)
            sigma = math.sqrt(self.sigma_shape ** 2 + self.sigma_day ** 2 * j)
            return Forecast(mu, sigma, None)

        return forecast


# ------------------------------------------------------------ Öffnungszeiten
class OpeningModel:
    """Öffnungswahrscheinlichkeit je Tankstelle, Tagestyp (0..6) und Stunde."""

    ALPHA = 0.15

    def __init__(self, data: dict | None = None) -> None:
        self.data: dict[str, list[list[float]]] = data or {}

    @staticmethod
    def _prior(hour: int) -> float:
        return 0.9 if 6 <= hour < 21 else 0.3

    def update(self, station: str, dt: datetime, is_open: bool, calendar: Calendar) -> None:
        dt = dt.astimezone(TZ)
        table = self.data.setdefault(station, [[self._prior(h) for h in range(24)] for _ in range(7)])
        typ = calendar.day_type(dt.date())
        old = table[typ][dt.hour]
        table[typ][dt.hour] = old + self.ALPHA * ((1.0 if is_open else 0.0) - old)

    def probability(self, station: str, dt: datetime, calendar: Calendar) -> float:
        dt = dt.astimezone(TZ)
        table = self.data.get(station)
        if not table:
            return self._prior(dt.hour)
        return table[calendar.day_type(dt.date())][dt.hour]

    def is_open(self, station: str, dt: datetime, calendar: Calendar) -> bool:
        return self.probability(station, dt, calendar) >= 0.5

    def open_until(self, station: str, dt: datetime, calendar: Calendar) -> int | None:
        """Erste Stunde ab dt, in der die Tankstelle typischerweise schließt."""
        dt = dt.astimezone(TZ)
        for hour in range(dt.hour, 24):
            if not self.is_open(station, dt.replace(hour=hour, minute=0), calendar):
                return hour
        return None  # bis Mitternacht oder durchgehend geöffnet

    def to_dict(self) -> dict:
        return self.data


# ---------------------------------------------------------------- Verbrauch
DEFAULT_PRIOR_KM = {0: 15.0, 1: 15.0, 2: 15.0, 3: 200.0, 4: 15.0, 5: 25.0, 6: 10.0}


class ConsumptionModel:
    """km je Tagestyp (aus Tagesabschlüssen des Kilometerstands) und l/100 km."""

    PRIOR_WEIGHT = 2.0
    HALF_LIFE = 42.0

    def __init__(self, data: dict | None = None, prior_km: dict | None = None,
                 prior_l100: float = 8.5) -> None:
        data = data or {}
        self.snapshots: dict[str, float] = data.get("snapshots", {})   # Datum -> km-Stand Tagesende
        self.km_days: dict[str, float] = data.get("km_days", {})       # Datum -> km
        self.l100: float = data.get("l100", prior_l100)
        self.l100_n: int = data.get("l100_n", 0)
        self.anchor: dict | None = data.get("anchor")                  # {"odo":…, "liter":…}
        self.last_odo: float | None = data.get("last_odo")
        self.prior_km = {int(k): float(v) for k, v in (prior_km or DEFAULT_PRIOR_KM).items()}

    # -- Kilometerstand
    def record_odometer(self, value: float) -> None:
        if self.last_odo is None or value >= self.last_odo:
            self.last_odo = value

    def close_day(self, day: date) -> None:
        """Tagesabschluss (kurz vor Mitternacht): km des Tages berechnen."""
        if self.last_odo is None:
            return
        self.snapshots[day.isoformat()] = self.last_odo
        prev = self.snapshots.get((day - timedelta(days=1)).isoformat())
        if prev is not None:
            km = self.last_odo - prev
            if 0 <= km < 1500:
                self.km_days[day.isoformat()] = km
        limit = (day - timedelta(days=180)).isoformat()
        for store in (self.snapshots, self.km_days):
            for key in [k for k in store if k < limit]:
                del store[key]

    def driven_today(self, today: date) -> float:
        prev = self.snapshots.get((today - timedelta(days=1)).isoformat())
        if prev is None or self.last_odo is None:
            return 0.0
        return max(0.0, self.last_odo - prev)

    def expected_km(self, day: date, calendar: Calendar) -> float:
        typ = calendar.day_type(day)
        prior = self.prior_km.get(typ, 15.0)
        if typ == 3 and not calendar.is_workday(day):
            prior = self.prior_km.get(SUNDAY_TYPE, 10.0)
        num = prior * self.PRIOR_WEIGHT
        den = self.PRIOR_WEIGHT
        for iso, km in self.km_days.items():
            d = date.fromisoformat(iso)
            if calendar.day_type(d) == typ and d < day:
                w = _weight((day - d).days, self.HALF_LIFE)
                num += w * km
                den += w
        return num / den

    def profile(self, calendar: Calendar, today: date) -> dict[int, float]:
        """Erwartete km je Tagestyp (für Anzeige)."""
        result = {}
        for offset in range(14):
            d = today + timedelta(days=offset)
            result.setdefault(calendar.day_type(d), round(self.expected_km(d, calendar), 1))
        return dict(sorted(result.items()))

    # -- Verbrauch
    def record_fuel(self, liters: float, odometer: float | None, refuel: bool = False) -> None:
        if odometer is None:
            return
        if refuel or self.anchor is None or liters > self.anchor["liter"] + 2:
            self.anchor = {"odo": odometer, "liter": liters}
            return
        km = odometer - self.anchor["odo"]
        used = self.anchor["liter"] - liters
        if km >= 80 and used > 0:
            sample = used / km * 100.0
            if 4.0 <= sample <= 20.0:
                alpha = max(0.2, 1.0 / (self.l100_n + 2))
                self.l100 += alpha * (sample - self.l100)
                self.l100_n += 1
            self.anchor = {"odo": odometer, "liter": liters}

    def to_dict(self) -> dict:
        return {"snapshots": self.snapshots, "km_days": self.km_days, "l100": self.l100,
                "l100_n": self.l100_n, "anchor": self.anchor, "last_odo": self.last_odo}


# ------------------------------------------------------------------ Helfer
def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _wmean(pairs: list[tuple[float, float]]) -> float:
    den = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / den if den else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def _slope(xs: list[float], ys: list[float]) -> float:
    mx, my = _mean(xs), _mean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0

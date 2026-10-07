"""Kalender für den Tank-Assistenten.

- Gesetzliche Feiertage Bayern (gleiche Regeln wie die Workday-Integration mit
  Land DE / Bundesland BY; Augsburger Friedensfest ist nicht enthalten).
- Schulferien Bayern über die OpenHolidays-API (https://openholidaysapi.org).
- Tagestypen: Mo..Sa = 0..5, Sonntag und Feiertag = 6.

Reines Python ohne Abhängigkeiten, damit es ohne AppDaemon testbar ist.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date, timedelta
from typing import Iterable

SUNDAY_TYPE = 6
DAY_NAMES = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So/Feiertag"]
OPENHOLIDAYS_URL = (
    "https://openholidaysapi.org/SchoolHolidays?countryIsoCode=DE"
    "&subdivisionCode={sub}&languageIsoCode=DE&validFrom={start}&validTo={end}"
)


def easter_sunday(year: int) -> date:
    """Ostersonntag nach dem Algorithmus von Meeus/Jones/Butcher."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def bavarian_holidays(year: int) -> dict[date, str]:
    """Gesetzliche Feiertage in Bayern (inkl. Mariä Himmelfahrt)."""
    easter = easter_sunday(year)
    return {
        date(year, 1, 1): "Neujahr",
        date(year, 1, 6): "Heilige Drei Könige",
        easter - timedelta(days=2): "Karfreitag",
        easter + timedelta(days=1): "Ostermontag",
        date(year, 5, 1): "Tag der Arbeit",
        easter + timedelta(days=39): "Christi Himmelfahrt",
        easter + timedelta(days=50): "Pfingstmontag",
        easter + timedelta(days=60): "Fronleichnam",
        date(year, 8, 15): "Mariä Himmelfahrt",
        date(year, 10, 3): "Tag der Deutschen Einheit",
        date(year, 11, 1): "Allerheiligen",
        date(year, 12, 25): "1. Weihnachtstag",
        date(year, 12, 26): "2. Weihnachtstag",
    }


def parse_openholidays(payload: Iterable[dict]) -> list[tuple[date, date, str]]:
    """Wandelt die Antwort der OpenHolidays-API in (start, ende, name) um."""
    result = []
    for item in payload:
        try:
            start = date.fromisoformat(item["startDate"])
            end = date.fromisoformat(item["endDate"])
        except (KeyError, ValueError):
            continue
        names = item.get("name") or []
        name = names[0].get("text", "Ferien") if names else "Ferien"
        result.append((start, end, name))
    return sorted(result)


def fetch_school_holidays(
    subdivision: str, start: date, end: date, timeout: float = 15.0
) -> list[tuple[date, date, str]]:
    """Lädt Schulferien von der OpenHolidays-API (blockierend)."""
    url = OPENHOLIDAYS_URL.format(sub=subdivision, start=start.isoformat(), end=end.isoformat())
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (feste URL)
        return parse_openholidays(json.loads(resp.read().decode("utf-8")))


class Calendar:
    """Feiertage, Ferien und Tagestypen."""

    def __init__(self, school_holidays: list[tuple[date, date, str]] | None = None) -> None:
        self._holiday_cache: dict[int, dict[date, str]] = {}
        # Einzeltage wie Buß- und Bettag zählen nicht als „Ferienbeginn“.
        self.school_holidays = [h for h in (school_holidays or []) if (h[1] - h[0]).days >= 2]

    def holiday_name(self, day: date) -> str | None:
        if day.year not in self._holiday_cache:
            self._holiday_cache[day.year] = bavarian_holidays(day.year)
        return self._holiday_cache[day.year].get(day)

    def is_holiday(self, day: date) -> bool:
        return self.holiday_name(day) is not None

    def is_workday(self, day: date) -> bool:
        return day.weekday() < 5 and not self.is_holiday(day)

    def day_type(self, day: date) -> int:
        """0..5 = Mo..Sa, 6 = Sonntag oder Feiertag."""
        if self.is_holiday(day) or day.weekday() == 6:
            return SUNDAY_TYPE
        return day.weekday()

    def is_school_holiday(self, day: date) -> bool:
        return any(start <= day <= end for start, end, _ in self.school_holidays)

    def flags(self, day: date) -> set[str]:
        """Kalender-Merkmale, die das Preisniveau beeinflussen können."""
        result: set[str] = set()
        # Vortag eines Feiertags (inkl. Freitag/Samstag vor einem langen Wochenende)
        if any(self.is_holiday(day + timedelta(days=n)) for n in (1, 2)
               if n == 1 or self.day_type(day + timedelta(days=1)) == SUNDAY_TYPE):
            result.add("vor_feiertag")
        for start, _end, _name in self.school_holidays:
            # Ferienbeginn: letzter Schultag davor bis einschließlich zweitem Ferientag
            if start - timedelta(days=2) <= day <= start + timedelta(days=1):
                result.add("ferienbeginn")
                break
        return result

from datetime import date, timedelta

import pytest
from synth import STATIONS, at, generate

from ta_calendar import Calendar, easter_sunday, parse_openholidays
from ta_metrics import RefuelDetector, aggregate, evaluate_refuel
from ta_model import (ConsumptionModel, DiscountRule, Discounts, OpeningModel, PriceModel,
                      phase, pricing_day_start)
from ta_optimizer import StationInfo, build_slots, expected_min, optimize
from ta_text import plan_message


# ------------------------------------------------------------------ Kalender
def test_easter_and_bavarian_holidays():
    assert easter_sunday(2026) == date(2026, 4, 5)
    cal = Calendar()
    assert cal.holiday_name(date(2026, 6, 4)) == "Fronleichnam"
    assert cal.is_holiday(date(2026, 8, 15))
    assert cal.day_type(date(2026, 10, 3)) == 6          # Feiertag wie Sonntag
    assert cal.day_type(date(2026, 10, 8)) == 3          # Donnerstag
    assert not cal.is_workday(date(2026, 11, 1))


def test_school_holidays_and_flags():
    payload = [{"startDate": "2026-11-02", "endDate": "2026-11-06", "name": [{"text": "Herbstferien"}]},
               {"startDate": "2026-11-18", "endDate": "2026-11-18", "name": [{"text": "Buß- und Bettag"}]}]
    cal = Calendar(parse_openholidays(payload))
    assert cal.is_school_holiday(date(2026, 11, 4))
    assert not cal.is_school_holiday(date(2026, 11, 18))  # Einzeltag ignoriert
    assert "ferienbeginn" in cal.flags(date(2026, 10, 31))
    assert "vor_feiertag" in cal.flags(date(2026, 10, 31))  # vor Allerheiligen (Sonntag)
    assert "vor_feiertag" in cal.flags(date(2026, 10, 2))


# ------------------------------------------------------------------- Zeit
def test_pricing_day_and_phase():
    assert pricing_day_start(at(2026, 10, 7, 11)).date() == date(2026, 10, 6)
    assert pricing_day_start(at(2026, 10, 7, 12)).date() == date(2026, 10, 7)
    assert phase(at(2026, 10, 7, 12)) == 0
    assert phase(at(2026, 10, 8, 11)) == 23


# ------------------------------------------------------------------ Modell
def test_price_model_learns_noon_pattern():
    now = at(2026, 10, 30, 9)
    hist = generate(now - timedelta(days=28), 28)
    model = PriceModel.fit(hist, Calendar(), now)
    assert model.days_of_data >= 25
    s = "sensor.esso_alpenstr_13_super"
    # direkt nach 12 Uhr teurer als kurz vor 12 Uhr
    assert model.shape_value(s, 2, 0) - model.shape_value(s, 2, 23) > 0.05
    assert model.offset["sensor.pinoil_alpenstrasse_5_super"] < model.offset[s]
    hours = model.cheapest_hours(Calendar(), now.date())
    assert set(hours) & {9, 10, 11}


def test_forecast_respects_noon_rule():
    now = at(2026, 10, 30, 13)
    hist = generate(now - timedelta(days=21), 21)
    model = PriceModel.fit(hist, Calendar(), now)
    current = {s: hist.price_at(s, now) for s in STATIONS}
    fc = model.forecaster(Calendar(), now, current)
    s = "sensor.esso_alpenstr_13_super"
    tomorrow_11 = fc(s, at(2026, 10, 31, 11))
    assert tomorrow_11.upper == current[s] and tomorrow_11.mu <= current[s]
    assert tomorrow_11.sigma == 0
    tomorrow_13 = fc(s, at(2026, 10, 31, 13))
    assert tomorrow_13.upper is None and tomorrow_13.sigma > 0
    assert tomorrow_13.mu > tomorrow_11.mu                 # Sprung um 12 Uhr


def test_opening_model():
    cal = Calendar()
    om = OpeningModel()
    for week in range(8):
        om.update("x", at(2026, 9, 6, 23) + timedelta(days=7 * week), False, cal)  # Sonntag 23 Uhr zu
    assert not om.is_open("x", at(2026, 11, 1, 23), cal)
    assert om.is_open("x", at(2026, 11, 2, 10), cal)


def test_consumption_learns_weekday_profile():
    cal = Calendar()
    cm = ConsumptionModel()
    odo = 10000.0
    day = date(2026, 6, 1)
    for _ in range(70):
        odo += 210 if cal.day_type(day) == 3 else 8
        cm.record_odometer(odo)
        cm.close_day(day)
        day += timedelta(days=1)
    assert cm.expected_km(date(2026, 8, 13), cal) > 150            # Donnerstag
    assert cm.expected_km(date(2026, 8, 12), cal) < 15             # Mittwoch
    assert cm.expected_km(date(2026, 8, 15), cal) < 15             # Feiertag (Sa) wie Sonntag


def test_consumption_l100():
    cm = ConsumptionModel()
    cm.record_fuel(50, 1000)
    cm.record_fuel(41, 1100)
    assert 8.5 <= cm.l100 <= 9.0


def test_discounts():
    d = Discounts([DiscountRule.from_config({"marke": "ESSO", "cent": 2, "bis": "2026-10-15"}),
                   DiscountRule.from_config({"marke": "ESSO", "cent": 1, "ab": "2026-10-16"}),
                   DiscountRule.from_config({"marke": "AGIP", "cent": 1})])
    assert d.cent("ESSO", date(2026, 10, 10)) == 2
    assert d.cent("ESSO", date(2026, 10, 20)) == 1
    assert d.cent("AGIP ENI", date(2026, 10, 20)) == 1
    assert d.cent("JET", date(2026, 10, 20)) == 0


# --------------------------------------------------------------- Optimierer
def test_expected_min():
    assert expected_min(1.0, 0.0, 0.5) == 0.5
    assert expected_min(1.0, 0.1, float("inf")) == 1.0
    assert expected_min(0.0, 1.0, 0.0) == pytest.approx(-0.3989, abs=1e-3)


def _plan(now, fuel_l, days_hist=21, km=None, trend=0.0):
    cal = Calendar()
    hist = generate(now - timedelta(days=days_hist), days_hist, trend=trend)
    model = PriceModel.fit(hist, cal, now)
    current = {s: hist.price_at(s, now) for s in STATIONS}
    infos = [StationInfo(s, s, b, 0.0, current[s], True) for s, (b, _o) in STATIONS.items()]
    fc = model.forecaster(cal, now, current)
    km = km or (lambda d: 200.0 if cal.is_workday(d) and d.weekday() == 3 else 10.0)
    slots, timeline = build_slots(now, fuel_l, 58, 0.0, km, 8.5, infos, fc,
                                  lambda s, t: True, lambda st, d: 0.0)
    return optimize(now, slots, timeline, fuel_l, 8.5)


def test_must_refuel_before_office_day():
    # Mittwoch 15 Uhr, 20 l: Donnerstag braucht ~17 l + Reserve 8,5 l -> heute tanken
    plan = _plan(at(2026, 10, 28, 15), 20.0)
    assert plan.status == "muss"
    assert plan.best.start.date() == date(2026, 10, 28)


def test_prefers_before_noon_when_tank_full_enough():
    # Montag 13 Uhr (direkt nach dem Sprung), Tank halb voll -> nicht jetzt
    plan = _plan(at(2026, 10, 26, 13), 30.0)
    assert plan.status in ("warten", "heute")
    assert not plan.now_ok
    assert plan.best.start.hour in (9, 10, 11) or plan.best.start.hour >= 18


def test_now_before_noon_is_attractive_when_prices_rise():
    # Montag 11 Uhr, wenig drin, Preise steigen täglich -> jetzt (vor dem Sprung) tanken
    plan = _plan(at(2026, 10, 26, 11), 14.0, trend=0.012)
    assert plan.status in ("muss", "jetzt")
    assert plan.now_ok
    assert plan.best.start.date() == date(2026, 10, 26)


def test_waits_when_prices_fall():
    # gleiche Lage, aber fallende Preise -> warten (spätestens Mittwoch)
    plan = _plan(at(2026, 10, 26, 11), 14.0, trend=-0.012)
    assert not plan.now_ok
    assert plan.best.start.date() > date(2026, 10, 26)
    assert plan.latest.date() == date(2026, 10, 28)


def test_plan_message_is_german_text():
    now = at(2026, 10, 26, 13)
    plan = _plan(now, 30.0)
    title, text = plan_message(plan, {"now": now, "station_names": {}, "fuel_pct": 52.0, "fuel_l": 30.0,
                                      "tomorrow_km": 10})
    assert title and "Tank 52 %" in text


# ------------------------------------------------------------------ Metriken
def test_refuel_detector():
    det = RefuelDetector(20.0)
    assert det.update(19.0) is None
    assert det.update(95.0) == pytest.approx(76.0)


def test_evaluate_refuel_decomposition():
    now = at(2026, 10, 30, 11)
    hist = generate(now - timedelta(days=10), 10)
    disc = Discounts([DiscountRule("ESSO", 1)])
    brands = {s: b for s, (b, _o) in STATIONS.items()}
    r = evaluate_refuel(history=hist, discounts=disc, brands=brands, names={},
                        station="sensor.pinoil_alpenstrasse_5_super", when=now, liters=40,
                        since=now - timedelta(days=7))
    assert r.saving_total > 0
    assert r.saving_total == pytest.approx(r.saving_timing + r.saving_station + r.saving_discount, abs=0.05)
    assert 0 < r.exploitation <= 1
    summary = aggregate([r.to_dict()], now)
    assert summary["monat"]["tankvorgaenge"] == 1


def test_history_keeps_last_value_of_hour():
    # 12:05 noch alter Preis (Tankerkönig-Takt 30 Min.), 12:35 neuer Preis nach dem Sprung
    from ta_model import PriceHistory
    h = PriceHistory()
    h.add("s", at(2026, 10, 7, 12, 5), 1.70)
    h.add("s", at(2026, 10, 7, 12, 35), 1.79)
    assert h.price_at("s", at(2026, 10, 7, 12, 50)) == 1.79

"""Simuliert zwei Wochen Betrieb: keine Abstürze, kein Nachrichten-Spam, Tank nie unter Reserve."""

import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "stubs"))

import tank_assistent  # noqa: E402
from synth import STATIONS, at, generate  # noqa: E402
from test_app import make_states  # noqa: E402

from ta_calendar import Calendar  # noqa: E402


def test_two_weeks_operation(tmp_path):
    cal = Calendar()
    start = at(2026, 10, 5, 0)
    full = generate(start - timedelta(days=21), 21 + 15, seed=5, trend=0.002)
    hist = generate(start - timedelta(days=21), 21, seed=5, trend=0.002)
    args = {"fahrzeug": {"tankstand": "sensor.tiguan_tankstand",
                         "kilometerstand": "sensor.tiguan_kilometerstand", "tankgroesse": 58},
            "rabatte": [{"marke": "ESSO", "cent": 1}], "datei": str(tmp_path / "s.json")}
    app = tank_assistent.TankAssistent(args, make_states(hist, start, 50.0), start)
    app.initialize()
    app.history = hist
    fuel, odo = 29.0, 12000.0
    min_fuel, refuels = fuel, 0
    t = start
    while t < start + timedelta(days=14):
        app.now = t
        for s in STATIONS:
            app.states[s]["state"] = str(full.price_at(s, t))
        if t.hour == 7:                                   # Fahrt des Tages
            km = 200 if (t.weekday() == 3 and cal.is_workday(t.date())) else 12
            fuel -= km * 8.5 / 100
            odo += km
            min_fuel = min(min_fuel, fuel)
            app.states["sensor.tiguan_kilometerstand"]["state"] = str(odo)
            app._on_vehicle("sensor.tiguan_kilometerstand", "state", None, str(odo), {})
            app._morning({})
        app.states["sensor.tiguan_tankstand"]["state"] = str(round(fuel / 58 * 100, 1))
        app._on_vehicle("sensor.tiguan_tankstand", "state", None, str(round(fuel / 58 * 100, 1)), {})
        app._tick({})
        app._replan({})
        # Nutzer folgt „muss“/„jetzt“/„bestätigt“ sofort
        last = app.events[-1][1] if app.events else None
        if last and last["kind"] in ("muss", "jetzt", "bestaetigt") and not last.get("_done"):
            last["_done"] = True
            app._on_action("e", {"action": "erledigt"}, {})
            fuel = 58.0
            refuels += 1
            app.states["sensor.tiguan_tankstand"]["state"] = "100.0"
            app._on_vehicle("sensor.tiguan_tankstand", "state", None, "100.0", {})
        # fällige Timer
        due = [x for x in app.timers if x[0] == "at" and x[2] <= t]
        for x in due:
            app.timers.remove(x)
            x[1](x[3])
        if t.hour == 23:
            app._close_day({})
        t += timedelta(hours=1)
    kinds = [e[1]["kind"] for e in app.events]
    per_day = len([k for k in kinds if k not in ("tankung",)]) / 14
    assert min_fuel > 0, "liegen geblieben"
    assert refuels >= 1
    assert per_day < 3, f"zu viele Meldungen: {kinds}"
    assert app.refuels and all(r["saving_total"] is not None for r in app.refuels)

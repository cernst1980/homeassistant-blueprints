"""Smoke-Test der AppDaemon-App mit Stub (Discovery, Planung, MQTT, Meldungen, Tanken)."""

import json
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "stubs"))

import tank_assistent  # noqa: E402
from synth import STATIONS, at, generate  # noqa: E402


def make_states(hist, now, fuel_pct=40.0, odo=12000.0):
    states = {
        "sensor.tiguan_tankstand": {"state": str(fuel_pct), "attributes": {}},
        "sensor.tiguan_kilometerstand": {"state": str(odo), "attributes": {}},
    }
    for entity_id, (brand, _off) in STATIONS.items():
        base = entity_id.split(".", 1)[1].rsplit("_", 1)[0]
        states[entity_id] = {"state": str(hist.price_at(entity_id, now)), "attributes": {
            "fuel_type": "e5", "station_name": base, "brand": brand, "street": "Teststr.",
            "house_number": "1"}}
        states[f"binary_sensor.{base}_status"] = {"state": "on", "attributes": {}}
    states["binary_sensor.irgendwas_status"] = {"state": "on", "attributes": {}}
    return states


def make_app(tmp_path, now, fuel_pct=40.0):
    hist = generate(now - timedelta(days=21), 21, trend=0.004)
    args = {
        "fahrzeug": {"tankstand": "sensor.tiguan_tankstand",
                     "kilometerstand": "sensor.tiguan_kilometerstand", "tankgroesse": 58},
        "rabatte": [{"marke": "ESSO", "cent": 2, "bis": "2026-10-15"},
                    {"marke": "ESSO", "cent": 1, "ab": "2026-10-16"},
                    {"marke": "AGIP", "cent": 1}],
        "datei": str(tmp_path / "state.json"),
    }
    app = tank_assistent.TankAssistent(args, make_states(hist, now, fuel_pct), now)
    app.initialize()
    app.history = hist
    return app


def test_startup_discovery_and_plan(tmp_path):
    now = at(2026, 10, 27, 13, 5)   # Dienstag nach dem 12-Uhr-Sprung
    app = make_app(tmp_path, now)
    assert len(app.stations) == 4
    assert all(m["status"] and m["status"].startswith("binary_sensor.") and "irgendwas" not in m["status"]
               for m in app.stations.values())
    cfg = json.loads(app.published["homeassistant/sensor/tank_assistent/zielpreis/config"])
    assert cfg["unique_id"] == "tank_assistent_zielpreis"
    app._replan({})
    state = json.loads(app.published["tank_assistent/state"])
    assert state["status"] in ("muss", "jetzt", "heute", "warten")
    assert state["zielpreis"] and state["empfohlene_tankstelle"]
    attrs = json.loads(app.published["tank_assistent/attr/status"])
    assert attrs["plan"] and "text" in attrs
    assert app.published["tank_assistent/status"] == "online"


def test_morning_message_before_office_day(tmp_path):
    now = at(2026, 10, 28, 7, 0)    # Mittwoch, morgen Bürotag
    app = make_app(tmp_path, now, fuel_pct=30.0)   # 17,4 l -> reicht nicht für Do
    app._morning({})
    kinds = [e[1]["kind"] for e in app.events if e[0] == "tank_assistent_notify"]
    assert "plan" in kinds
    event = [e[1] for e in app.events if e[1]["kind"] == "plan"][-1]
    assert event["title"] == "Heute tanken"
    assert "morgen" in event["message"]
    facts = json.loads(event["facts"])
    assert facts["status"] == "muss"


def test_refuel_detection_and_savings(tmp_path):
    now = at(2026, 10, 29, 18, 0)
    app = make_app(tmp_path, now, fuel_pct=20.0)
    app._replan({})
    app._on_vehicle("sensor.tiguan_tankstand", "state", "20", "20.0", {})
    app._on_action("tank_assistent_action", {"action": "erledigt"}, {})
    app.now = now + timedelta(hours=1)
    app.states["sensor.tiguan_tankstand"]["state"] = "95.0"
    app._on_vehicle("sensor.tiguan_tankstand", "state", "20.0", "95.0", {})
    assert len(app.refuels) == 1
    r = app.refuels[0]
    assert r["source"] == "bestaetigt" and 40 < r["liters"] < 46
    assert r["saving_total"] is not None
    kinds = [e[1]["kind"] for e in app.events]
    assert "tankung" in kinds
    # Zustand wird gespeichert und wieder geladen
    app2 = tank_assistent.TankAssistent(app.args, app.states, app.now)
    app2.initialize()
    assert len(app2.refuels) == 1 and app2.history.stations()


def test_lead_reminder_confirms(tmp_path):
    now = at(2026, 10, 26, 13, 0)
    app = make_app(tmp_path, now, fuel_pct=45.0)
    app._replan({})
    best = app.plan.best
    app.now = best.start - timedelta(minutes=60)
    app._lead_reminder({"slot": best.start.isoformat()})
    kinds = [e[1]["kind"] for e in app.events]
    assert kinds and kinds[-1] in ("bestaetigt", "abgesagt")


def test_restart_reschedules_reminder(tmp_path):
    now = at(2026, 10, 26, 13, 0)
    app = make_app(tmp_path, now, fuel_pct=30.0)
    app.notes["reminder_for"] = "2026-10-27T11:00:00+01:00"
    app._save()
    app2 = tank_assistent.TankAssistent(app.args, app.states, now)
    app2.initialize()
    assert "reminder_for" not in app2.notes


def test_station_buttons_and_action(tmp_path):
    now = at(2026, 10, 28, 10, 0)
    app = make_app(tmp_path, now, fuel_pct=30.0)
    app._replan({})
    app._send_plan("plan")
    ev = app.events[-1][1]
    assert ev["actions"] and ev["buttons"][-1]["action"] == "TANK_SPAETER"
    station = ev["buttons"][1]["action"].split(":", 1)[1]
    assert station in app.stations
    app._on_action("tank_assistent_action", {"action": "erledigt", "station": station}, {})
    assert app.notes["done_station"] == station


def test_weekend_plan_time(tmp_path):
    now = at(2026, 10, 31, 7, 0)            # Samstag
    app = make_app(tmp_path, now, fuel_pct=20.0)
    app.plan_time_free = "08:30:00"
    app._morning({"tag": "werktag"})
    assert not app.events                  # Werktags-Lauf greift am Samstag nicht
    app._morning({"tag": "frei"})
    assert app.events


def test_evening_check_only_when_tight(tmp_path):
    now = at(2026, 10, 28, 19, 0)           # Mittwoch, morgen Bürotag
    app = make_app(tmp_path, now, fuel_pct=80.0)
    app._evening({})
    assert not app.events                  # genug Sprit
    app.states["sensor.tiguan_tankstand"]["state"] = "30.0"
    app._evening({})
    assert app.events and app.events[-1][1]["kind"] == "muss"

"""Tank-Assistent – AppDaemon-App.

Lernt Preisprofile, Öffnungszeiten und das eigene Fahrprofil, plant den günstigsten
Tankzeitpunkt (optimales Stoppproblem) und stellt alles per MQTT Discovery als
Home-Assistant-Entitäten bereit. Benachrichtigungen werden als Event
`tank_assistent_notify` ausgelöst und vom Blueprint verschickt (inkl. Gemini-Text).

Konfiguration: siehe tank_assistent.yaml.example und docs/tank_assistent.md im Repo.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timedelta

import appdaemon.plugins.hass.hassapi as hass

from ta_calendar import DAY_NAMES, Calendar, fetch_school_holidays
from ta_metrics import RefuelDetector, aggregate, evaluate_refuel
from ta_model import (TZ, ConsumptionModel, DiscountRule, Discounts, OpeningModel,
                      PriceHistory, PriceModel)
from ta_optimizer import StationInfo, build_slots, optimize
from ta_text import _cap, euro, plan_message, refuel_message, weekly_message, when_label

VERSION = "1.0.0"
STATE_VERSION = 1
EVENT_NOTIFY = "tank_assistent_notify"
EVENT_ACTION = "tank_assistent_action"
DAY_KEYS = ["mo", "di", "mi", "do", "fr", "sa", "so"]


class TankAssistent(hass.Hass):
    # ================================================================ Start
    def initialize(self) -> None:
        self._lock = threading.RLock()
        a = self.args
        car = a.get("fahrzeug", {})
        self.fuel_entity = car.get("tankstand")
        self.odo_entity = car.get("kilometerstand")
        self.l100_entity = car.get("verbrauch")
        self.capacity = float(car.get("tankgroesse", 58))
        self.reserve_km = float(a.get("reserve_km", 100))
        hours = a.get("verfuegbar", {})
        self.hours = (int(hours.get("von", 6)), int(hours.get("bis", 22)))
        # An Tagen mit langer Fahrt (z. B. Bürotag) bin ich tagsüber unterwegs
        long_day = a.get("fahrtag", {})
        self.long_day_km = float(long_day.get("ab_km", 100))
        self.long_day_windows = [tuple(int(x) for x in w) for w in
                                 long_day.get("verfuegbar", [[6, 7], [18, 22]])]
        self.min_advantage = float(a.get("min_vorteil_jetzt", 0.5))
        self.horizon = int(a.get("horizont_tage", 10))
        self.fuel_type = str(a.get("sorte", "e5")).lower()
        self.region = a.get("ferien_region", "DE-BY")
        n = a.get("benachrichtigung", {})
        self.plan_time = str(n.get("plan_uhrzeit", "07:00:00"))
        self.lead = int(n.get("vorlauf_min", 60))
        self.quiet = (int(n.get("ruhe_von", 21)), int(n.get("ruhe_bis", 7)))
        self.spont_gap = float(n.get("spontan_abstand_h", 3))
        self.spont_min = float(n.get("spontan_min_vorteil", 1.0))
        self.weekly_time = str(n.get("wochenbilanz_uhrzeit", "18:00:00"))
        self.notify_refuel = bool(n.get("tankung_melden", True))
        self.prefix = str(a.get("mqtt_prefix", "tank_assistent"))
        self.discovery_prefix = str(a.get("mqtt_discovery_prefix", "homeassistant"))
        self.discounts = Discounts([DiscountRule.from_config(r) for r in a.get("rabatte", [])])

        prior = a.get("km_start", {})
        prior_km = {i: float(prior.get(k, d)) for i, (k, d) in
                    enumerate(zip(DAY_KEYS, [15, 15, 15, 200, 15, 25, 10]))}
        self.state_file = a.get("datei") or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "tank_assistent.json")

        s = self._load()
        self.history = PriceHistory(s.get("history"))
        self.opening = OpeningModel(s.get("opening"))
        self.consumption = ConsumptionModel(s.get("consumption"), prior_km,
                                            float(a.get("verbrauch_start", 8.5)))
        self.detector = RefuelDetector(s.get("last_pct"))
        self.refuels: list[dict] = s.get("refuels", [])
        self.notes: dict = s.get("notes", {})
        self.school = [(date.fromisoformat(x[0]), date.fromisoformat(x[1]), x[2])
                       for x in s.get("school", [])]
        self.school_loaded = s.get("school_loaded")
        self.last_fuel_time = s.get("last_fuel_time")
        self.calendar = Calendar(self.school)

        self.plan = None
        self.model: PriceModel | None = None
        self.stations: dict[str, dict] = {}
        self._reminder = None
        self._debounce = None

        self._discover_stations()
        self._publish_discovery()
        self._mqtt(f"{self.prefix}/status", "online")

        for entity in filter(None, [self.fuel_entity, self.odo_entity]):
            self.listen_state(self._on_vehicle, entity)
        self.listen_event(self._on_action, EVENT_ACTION)

        start = self.get_now() + timedelta(seconds=15)
        self.run_every(self._tick, start, 15 * 60)
        self.run_daily(self._close_day, "23:58:00")
        self.run_daily(self._morning, self.plan_time)
        self.run_daily(self._weekly, self.weekly_time)
        self.run_daily(self._refresh_holidays, "03:17:00")
        self.run_daily(self._discover_tick, "04:05:00")
        if not self.school_loaded or self.school_loaded < (date.today() - timedelta(days=7)).isoformat():
            self.run_in(self._refresh_holidays, 20)
        self.run_in(self._replan, 30)
        self.log(f"Tank-Assistent {VERSION} gestartet, {len(self.stations)} Tankstellen")

    def terminate(self) -> None:
        try:
            self._mqtt(f"{self.prefix}/status", "offline")
            self._save()
        except Exception as err:  # noqa: BLE001
            self.log(f"Beenden: {err}", level="WARNING")

    # ======================================================== Persistenz
    def _load(self) -> dict:
        try:
            with open(self.state_file, encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("version") == STATE_VERSION:
                return data
        except FileNotFoundError:
            pass
        except Exception as err:  # noqa: BLE001
            self.log(f"Zustand nicht lesbar ({err}), starte neu", level="WARNING")
        return {}

    def _save(self) -> None:
        with self._lock:
            data = {
                "version": STATE_VERSION,
                "history": self.history.to_dict(),
                "opening": self.opening.to_dict(),
                "consumption": self.consumption.to_dict(),
                "last_pct": self.detector.last_pct,
                "refuels": self.refuels[-400:],
                "notes": self.notes,
                "school": [[a.isoformat(), b.isoformat(), c] for a, b, c in self.school],
                "school_loaded": self.school_loaded,
                "last_fuel_time": self.last_fuel_time,
            }
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            tmp = self.state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, separators=(",", ":"))
            os.replace(tmp, self.state_file)

    # ========================================================= Tankstellen
    def _discover_tick(self, kwargs) -> None:
        self._discover_stations()

    def _discover_stations(self) -> None:
        cfg = self.args.get("tankstellen", "auto")
        stations: dict[str, dict] = {}
        if isinstance(cfg, list):
            for item in cfg:
                stations[item["preis"]] = {"status": item.get("status")}
        else:
            sensors = self.get_state("sensor") or {}
            binaries = self.get_state("binary_sensor") or {}
            for entity_id, st in sensors.items():
                attrs = (st or {}).get("attributes", {})
                if str(attrs.get("fuel_type", "")).lower() == self.fuel_type and "station_name" in attrs:
                    stations[entity_id] = {"status": self._match_status(entity_id, binaries)}
        for entity_id, info in stations.items():
            attrs = self.get_state(entity_id, attribute="all") or {}
            a = attrs.get("attributes", {})
            brand = a.get("brand") or ""
            street = f"{a.get('street', '')} {a.get('house_number', '') or ''}".strip()
            info["brand"] = brand
            info["name"] = f"{brand} {street.title()}".strip() or entity_id
        new = set(stations) - set(self.stations)
        for entity_id in new:
            self.listen_state(self._on_price, entity_id)
            if stations[entity_id].get("status"):
                self.listen_state(self._on_price, stations[entity_id]["status"])
        self.stations = stations
        if new:
            self.log(f"Tankstellen: {', '.join(i['name'] for i in stations.values())}")

    @staticmethod
    def _match_status(price_entity: str, binaries: dict) -> str | None:
        base = price_entity.split(".", 1)[1].rsplit("_", 1)[0]
        for entity_id in binaries:
            obj = entity_id.split(".", 1)[1]
            if obj.rsplit("_", 1)[0] == base:
                return entity_id
        return None

    def _price(self, entity_id: str) -> float | None:
        try:
            value = float(self.get_state(entity_id))
            return value if 0.5 < value < 5 else None
        except (TypeError, ValueError):
            return None

    def _open_now(self, entity_id: str) -> bool | None:
        status = self.stations.get(entity_id, {}).get("status")
        if not status:
            return None
        value = self.get_state(status)
        return {"on": True, "off": False}.get(value)

    # ============================================================== Events
    def _on_price(self, entity, attribute, old, new, kwargs) -> None:
        if self._debounce:
            self._cancel(self._debounce)
        self._debounce = self.run_in(self._replan, 60)

    def _on_vehicle(self, entity, attribute, old, new, kwargs) -> None:
        now = self._now()
        try:
            value = float(new)
        except (TypeError, ValueError):
            return
        with self._lock:
            if entity == self.odo_entity:
                self.consumption.record_odometer(value)
            elif entity == self.fuel_entity:
                prev_time = self.last_fuel_time
                rise = self.detector.update(value)
                liters = value / 100.0 * self.capacity
                self.consumption.record_fuel(liters, self.consumption.last_odo, refuel=rise is not None)
                self.last_fuel_time = now.isoformat()
                if rise is not None:
                    self._handle_refuel(rise / 100.0 * self.capacity, now, prev_time)
        self._save()
        self.run_in(self._replan, 5)

    def _on_action(self, event_name, data, kwargs) -> None:
        action = (data or {}).get("action")
        now = self._now()
        if action == "erledigt":
            self.notes["done"] = now.isoformat()
            if self.plan and self.plan.best:
                self.notes["done_station"] = self.plan.now_station or self.plan.best.station
            self._cancel(self._reminder)
        elif action == "spaeter":
            self.notes["snooze_until"] = (now + timedelta(hours=2)).isoformat()
            self.run_in(self._snooze_end, 2 * 3600)
        self._save()

    def _snooze_end(self, kwargs) -> None:
        self._compute_safe()
        if self.plan and self.plan.status in ("muss", "jetzt", "heute") and not self._done_recently():
            self._send_plan("erinnerung")

    # ============================================================== Takt
    def _tick(self, kwargs) -> None:
        now = self._now()
        with self._lock:
            for entity_id in self.stations:
                price = self._price(entity_id)
                is_open = self._open_now(entity_id)
                if price is not None and is_open is not False:
                    self.history.add(entity_id, now, price)
                if is_open is not None:
                    self.opening.update(entity_id, now, is_open, self.calendar)
            self.history.prune(now)
        self._save()

    def _close_day(self, kwargs) -> None:
        with self._lock:
            self.consumption.close_day(self._now().date())
        self._save()

    def _refresh_holidays(self, kwargs) -> None:
        today = date.today()
        try:
            school = fetch_school_holidays(self.region, today - timedelta(days=400),
                                           today + timedelta(days=400))
        except Exception as err:  # noqa: BLE001
            self.log(f"Schulferien nicht abrufbar: {err}", level="WARNING")
            return
        with self._lock:
            self.school = school
            self.school_loaded = today.isoformat()
            self.calendar = Calendar(school)
        self._save()

    # ============================================================ Planung
    def _now(self) -> datetime:
        return self.get_now().astimezone(TZ)

    def _fuel(self) -> tuple[float | None, float | None]:
        """(Prozent, Liter) – bei fehlendem Sensor Schätzung aus dem letzten Wert."""
        try:
            pct = float(self.get_state(self.fuel_entity))
            return pct, pct / 100.0 * self.capacity
        except (TypeError, ValueError):
            pct = self.detector.last_pct
            if pct is None:
                return None, None
            liters = pct / 100.0 * self.capacity
            anchor = self.consumption.anchor
            if anchor and self.consumption.last_odo is not None:
                liters -= max(0.0, self.consumption.last_odo - anchor["odo"]) * self.consumption.l100 / 100
            return liters / self.capacity * 100.0, max(0.0, liters)

    def _l100(self) -> float:
        try:
            value = float(self.get_state(self.l100_entity)) if self.l100_entity else None
            if value and 4 <= value <= 20 and self.consumption.l100_n < 3:
                return value
        except (TypeError, ValueError):
            pass
        return self.consumption.l100

    def _replan(self, kwargs) -> None:
        if self._compute_safe():
            self._after_plan()

    def _compute_safe(self) -> bool:
        with self._lock:
            try:
                self._compute()
                return True
            except Exception as err:  # noqa: BLE001
                self.log(f"Planung fehlgeschlagen: {err}", level="ERROR")
                return False

    def _compute(self) -> None:
        now = self._now()
        today = now.date()
        pct, liters = self._fuel()
        l100 = self._l100()
        self.model = PriceModel.fit(self.history, self.calendar, now)
        infos = []
        current = {}
        for entity_id, meta in self.stations.items():
            price = self._price(entity_id)
            if price is not None:
                current[entity_id] = price
            infos.append(StationInfo(entity_id, meta["name"], meta["brand"],
                                     self.discounts.euro(meta["brand"], today), price,
                                     self._open_now(entity_id)))
        if liters is None or not current:
            self.plan = None
            self._publish_state(now, pct, liters, l100)
            return
        forecast = self.model.forecaster(self.calendar, now, current)
        km_today = self.consumption.expected_km(today, self.calendar)
        remaining = max(0.0, km_today - self.consumption.driven_today(today))
        slots, timeline = build_slots(
            now, liters, self.capacity, remaining,
            lambda d: self.consumption.expected_km(d, self.calendar), l100, infos, forecast,
            lambda s, t: self.opening.is_open(s, t, self.calendar),
            lambda st, d: self.discounts.euro(st.brand, d), self.hours, self.horizon,
            self._windows_for_day)
        reserve_l = self.reserve_km * l100 / 100.0
        self.plan = optimize(now, slots, timeline, liters, reserve_l, self.min_advantage)
        self._publish_state(now, pct, liters, l100)

    # ======================================================== MQTT / Entitäten
    SENSORS = [
        # key, name, unit, device_class, icon, state_class
        ("status", "Status", None, None, "mdi:gas-station", None),
        ("empfehlung", "Empfehlung", None, None, "mdi:message-text", None),
        ("zielpreis", "Zielpreis", "€/L", None, "mdi:target", None),
        ("empfohlener_zeitpunkt", "Empfohlener Zeitpunkt", None, "timestamp", "mdi:clock-check", None),
        ("empfohlene_tankstelle", "Empfohlene Tankstelle", None, None, "mdi:map-marker", None),
        ("spaetestens", "Spätestens tanken", None, "timestamp", "mdi:clock-alert", None),
        ("reserve_erreicht", "Reserve erreicht", None, "timestamp", "mdi:gauge-empty", None),
        ("bestpreis", "Bestpreis jetzt", "€/L", None, "mdi:currency-eur", "measurement"),
        ("bestpreis_tankstelle", "Bestpreis Tankstelle", None, None, "mdi:gas-station-outline", None),
        ("tankinhalt", "Tankinhalt", "L", "volume_storage", "mdi:fuel", "measurement"),
        ("reichweite", "Reichweite (berechnet)", "km", "distance", "mdi:map-marker-distance", "measurement"),
        ("preistrend", "Preistrend", None, None, "mdi:trending-up", None),
        ("trend_cent", "Preistrend (ct)", "ct", None, "mdi:chart-line", "measurement"),
        ("verbrauch", "Verbrauch", "L/100km", None, "mdi:fuel", "measurement"),
        ("km_morgen", "Erwartete km morgen", "km", "distance", "mdi:road-variant", None),
        ("ersparnis_monat", "Ersparnis Monat", "EUR", "monetary", "mdi:piggy-bank", None),
        ("ersparnis_jahr", "Ersparnis Jahr", "EUR", "monetary", "mdi:piggy-bank", None),
        ("ersparnis_gesamt", "Ersparnis gesamt", "EUR", "monetary", "mdi:piggy-bank", "total"),
        ("ausschoepfung", "Ausschöpfung", "%", None, "mdi:percent", None),
        ("letzte_tankung", "Letzte Tankung", None, "timestamp", "mdi:history", None),
        ("lernstand", "Lernstand (Preistage)", "d", None, "mdi:school", None),
    ]

    def _publish_discovery(self) -> None:
        device = {"identifiers": [self.prefix], "name": "Tank-Assistent",
                  "manufacturer": "cernst1980/homeassistant-blueprints", "model": "AppDaemon",
                  "sw_version": VERSION}
        for key, name, unit, dclass, icon, sclass in self.SENSORS:
            cfg = {
                "name": name,
                "unique_id": f"{self.prefix}_{key}",
                "default_entity_id": f"sensor.{self.prefix}_{key}",
                "state_topic": f"{self.prefix}/state",
                "value_template": f"{{{{ value_json.{key} }}}}",
                "availability_topic": f"{self.prefix}/status",
                "icon": icon,
                "device": device,
            }
            if key in ("status", "letzte_tankung"):
                cfg["json_attributes_topic"] = f"{self.prefix}/attr/{key}"
            if unit:
                cfg["unit_of_measurement"] = unit
            if dclass:
                cfg["device_class"] = dclass
            if sclass:
                cfg["state_class"] = sclass
            self._mqtt(f"{self.discovery_prefix}/sensor/{self.prefix}/{key}/config", json.dumps(cfg))

    def _mqtt(self, topic: str, payload: str) -> None:
        self.call_service("mqtt/publish", topic=topic, payload=payload, retain=True)

    def _publish_state(self, now, pct, liters, l100) -> None:
        plan = self.plan
        model = self.model
        names = {e: m["name"] for e, m in self.stations.items()}
        summary = aggregate(self.refuels, now)
        tomorrow = now.date() + timedelta(days=1)
        state = {
            "status": plan.status if plan else "unbekannt",
            "empfehlung": None,
            "zielpreis": None, "empfohlener_zeitpunkt": None, "empfohlene_tankstelle": None,
            "spaetestens": None, "reserve_erreicht": None, "bestpreis": None,
            "bestpreis_tankstelle": None,
            "tankinhalt": round(liters, 1) if liters is not None else None,
            "reichweite": round(liters / l100 * 100) if liters is not None else None,
            "preistrend": model.trend_label() if model else None,
            "trend_cent": round(model.trend_short_long * 100, 1) if model else None,
            "verbrauch": round(l100, 2),
            "km_morgen": round(self.consumption.expected_km(tomorrow, self.calendar)),
            "ersparnis_monat": summary["monat"]["ersparnis"],
            "ersparnis_jahr": summary["jahr"]["ersparnis"],
            "ersparnis_gesamt": summary["gesamt"]["ersparnis"],
            "ausschoepfung": round(summary["jahr"]["ausschoepfung"] * 100)
            if summary["jahr"]["ausschoepfung"] is not None else None,
            "letzte_tankung": self.refuels[-1]["time"] if self.refuels else None,
            "lernstand": model.days_of_data if model else 0,
        }
        best_now = None
        for entity_id, meta in self.stations.items():
            price = self._price(entity_id)
            if price is None or self._open_now(entity_id) is False:
                continue
            eff = price - self.discounts.euro(meta["brand"], now.date())
            if best_now is None or eff < best_now[1]:
                best_now = (entity_id, eff)
        if best_now:
            state["bestpreis"] = round(best_now[1], 3)
            state["bestpreis_tankstelle"] = names[best_now[0]]
        attrs: dict = {"version": VERSION, "aktualisiert": now.isoformat()}
        if plan and plan.best:
            title, text = plan_message(plan, self._ctx(now, pct, liters))
            state.update({
                "empfehlung": f"{title}: {text}"[:250],
                "zielpreis": round(_cap(plan.best), 3),
                "empfohlener_zeitpunkt": plan.best.start.isoformat(),
                "empfohlene_tankstelle": names.get(plan.best.station, plan.best.station),
                "spaetestens": plan.latest.isoformat() if plan.latest and not plan.truncated else None,
                "reserve_erreicht": plan.reserve_at.isoformat() if plan.reserve_at else None,
            })
            attrs.update({
                "titel": title, "text": text,
                "jetzt_tanken_optimal": plan.now_ok,
                "vorteil_jetzt_eur": round(plan.now_advantage_eur, 2),
                "erwarteter_preis": round(plan.best.mu, 3),
                "langfristiger_preis": round(plan.p_lr, 3) if plan.p_lr else None,
                "preis_garantiert_bis": plan.guaranteed_until.isoformat() if plan.guaranteed_until else None,
                "liter_beim_tanken": round(plan.best.liters, 1),
                "fahrprofil_km": {DAY_NAMES[k]: v for k, v in
                                  self.consumption.profile(self.calendar, now.date()).items()},
                "guenstigste_uhrzeiten": model.cheapest_hours(self.calendar, now.date()) if model else [],
                "trend_steigung_ct_tag": round(model.slope * 100, 2) if model else None,
                "effekte_ct": {k: round(v * 100, 2) for k, v in (model.effects if model else {}).items()},
                "plan": [
                    {"zeit": s.start.isoformat(), "tankstelle": names.get(s.station, s.station),
                     "erwartet": round(s.mu, 3),
                     "zielpreis": None if abs(s.reservation) == float("inf") else round(s.reservation, 3),
                     "wahrscheinlichkeit": round(s.stop_probability, 3)}
                    for s in sorted(plan.slots, key=lambda x: -x.stop_probability)[:8] if s.stop_probability > 0
                ],
            })
        self._mqtt(f"{self.prefix}/state", json.dumps(state))
        self._mqtt(f"{self.prefix}/attr/status", json.dumps(attrs))
        if self.refuels:
            self._mqtt(f"{self.prefix}/attr/letzte_tankung",
                       json.dumps({**self.refuels[-1], "summen": summary}))

    def _ctx(self, now, pct, liters) -> dict:
        tomorrow = now.date() + timedelta(days=1)
        km_tomorrow = self.consumption.expected_km(tomorrow, self.calendar)
        l100 = self._l100()
        reserve_l = self.reserve_km * l100 / 100
        km_today = max(0.0, self.consumption.expected_km(now.date(), self.calendar)
                       - self.consumption.driven_today(now.date()))
        left = (liters or 0) - (km_today + km_tomorrow) * l100 / 100
        names = {e: m["name"] for e, m in self.stations.items()}
        open_until = {}
        if self.plan and self.plan.best:
            s = self.plan.best.station
            open_until[s] = self.opening.open_until(s, self.plan.best.start, self.calendar)
        station = self.plan.now_station if self.plan and self.plan.status == "jetzt" else (
            self.plan.best.station if self.plan and self.plan.best else None)
        brand = self.stations.get(station, {}).get("brand") if station else None
        return {
            "now": now, "station_names": names, "open_until": open_until,
            "tomorrow_km": km_tomorrow,
            "tomorrow_day": DAY_NAMES[self.calendar.day_type(tomorrow)],
            "tomorrow_ok": left >= reserve_l,
            # Reserve wird zu Tagesbeginn erreicht -> der Tag davor ist der letzte volle Tag
            "range_until": (self.plan.reserve_at - timedelta(minutes=1)).date()
            if self.plan and self.plan.reserve_at else None,
            "fuel_pct": pct, "fuel_l": liters,
            "discount_hint": self.discounts.cent(brand, now.date()) > 0 if brand else False,
        }

    # ===================================================== Benachrichtigungen
    def _quiet(self, now: datetime) -> bool:
        start, end = self.quiet
        return now.hour >= start or now.hour < end

    def _windows_for_day(self, day: date) -> list[tuple[int, int]]:
        if self.consumption.expected_km(day, self.calendar) >= self.long_day_km:
            return self.long_day_windows
        return [self.hours]

    def _done_recently(self) -> bool:
        refueled = self.notes.get("refueled")
        if refueled and self._now() - datetime.fromisoformat(refueled) < timedelta(hours=12):
            return True
        done = self.notes.get("done")
        return bool(done) and self._now() - datetime.fromisoformat(done) < timedelta(hours=12)

    def _snoozed(self) -> bool:
        until = self.notes.get("snooze_until")
        return bool(until) and self._now() < datetime.fromisoformat(until)

    def _signature(self) -> str | None:
        p = self.plan
        if not p or not p.best:
            return None
        return f"{p.status}|{p.best.start:%Y-%m-%d}|{p.best.station}|{round(_cap(p.best), 2)}"

    def _after_plan(self) -> None:
        """Spontane Meldungen und Vorlauf-Erinnerung nach jeder Neuplanung."""
        plan = self.plan
        now = self._now()
        if not plan or not plan.best or self._done_recently():
            return
        # Vorlauf-Erinnerung für den geplanten Zeitpunkt
        target = plan.best.start - timedelta(minutes=self.lead)
        if plan.best.start > now + timedelta(minutes=self.lead) and plan.best.start - now < timedelta(days=2):
            key = plan.best.start.isoformat()
            if self.notes.get("reminder_for") != key and self.notes.get("reminded") != key:
                self._cancel(self._reminder)
                self._reminder = self.run_at(self._lead_reminder, target, slot=key)
                self.notes["reminder_for"] = key
        if self._snoozed() or (self._quiet(now) and plan.status != "muss"):
            return
        # Zeitpunkt ist näher als die Vorlaufzeit gerückt -> einmalig jetzt erinnern
        key = plan.best.start.isoformat()
        if (timedelta(0) < plan.best.start - now <= timedelta(minutes=self.lead)
                and plan.status in ("heute", "muss") and self.notes.get("reminded") != key
                and self.notes.get("reminder_for") != key and not self._quiet(now)):
            self.notes["reminded"] = key
            self._send_plan("bestaetigt")
        last = self.notes.get("last_spontaneous")
        gap_ok = not last or now - datetime.fromisoformat(last) >= timedelta(hours=self.spont_gap)
        if plan.status == "muss" and self.notes.get("muss_sent") != now.date().isoformat() \
                and not self._quiet(now):
            self.notes["muss_sent"] = now.date().isoformat()
            self._send_plan("muss")
        elif plan.status == "jetzt" and gap_ok and plan.now_advantage_eur >= self.spont_min \
                and self.notes.get("last_status") != "jetzt":
            self.notes["last_spontaneous"] = now.isoformat()
            self._send_plan("jetzt")
        self.notes["last_status"] = plan.status
        self._save()

    def _morning(self, kwargs) -> None:
        self._compute_safe()
        plan = self.plan
        if not plan or not plan.best:
            return
        now = self._now()
        tomorrow = now.date() + timedelta(days=1)
        long_drive = self.consumption.expected_km(tomorrow, self.calendar) >= 100
        soon = (plan.best.start.date() - now.date()).days <= 2
        changed = soon and self._signature() != self.notes.get("last_plan_sig")
        if plan.status in ("muss", "jetzt", "heute") or changed or long_drive:
            if plan.status == "muss":
                self.notes["muss_sent"] = now.date().isoformat()
            if plan.status == "jetzt":
                self.notes["last_spontaneous"] = now.isoformat()
            self._send_plan("plan")
        self.notes["last_status"] = plan.status
        self._after_plan()          # Vorlauf-Erinnerung planen (keine Doppelmeldung)

    def _lead_reminder(self, kwargs) -> None:
        self.notes.pop("reminder_for", None)
        slot_iso = kwargs.get("slot")
        self.notes["reminded"] = slot_iso
        old_target = None
        if self.plan and self.plan.best and self.plan.best.start.isoformat() == slot_iso:
            old_target = _cap(self.plan.best)
        self._compute_safe()
        plan = self.plan
        if not plan or not plan.best or self._done_recently():
            return
        now = self._now()
        names = {e: m["name"] for e, m in self.stations.items()}
        slot_start = datetime.fromisoformat(slot_iso) if slot_iso else plan.best.start
        # Bestätigt, wenn der neue Plan weiterhin bis spätestens zum geplanten Termin tanken will
        go = plan.status in ("jetzt", "muss") or (
            plan.status == "heute" and plan.best.start <= slot_start + timedelta(hours=1))
        if plan.status == "jetzt" and plan.now_station:
            station_id, expected = plan.now_station, plan.now_price
        else:
            station_id, expected = plan.best.station, plan.best.mu
        station = names.get(station_id, station_id)
        if go:
            when = "jetzt" if plan.status == "jetzt" else when_label(plan.best.start, now)
            title = f"Tanken {when} – wie geplant" if old_target and expected <= old_target + 0.002 \
                else f"Tanken {when}"
            text = f"{station}: {euro(expected)}"
            if old_target:
                text += f" (Ziel war ≤ {euro(old_target)})"
            text += "."
            if plan.guaranteed_until:
                text += f" Der Preis kann bis {plan.guaranteed_until:%H:%M} Uhr nur noch fallen."
            kind = "bestaetigt"
        else:
            reason = ("Preis höher als erwartet" if old_target and expected > old_target + 0.002
                      else "später voraussichtlich günstiger")
            title = f"Noch nicht tanken – {reason}"
            text = (f"Neuer Plan: {when_label(plan.best.start, now)} bei {station}, "
                    f"wenn höchstens {euro(_cap(plan.best))}.")
            kind = "abgesagt"
        self._fire(kind, title, text, actions=(kind == "bestaetigt"))

    def _weekly(self, kwargs) -> None:
        now = self._now()
        if now.weekday() != 6:
            return
        self._compute_safe()
        summary = aggregate(self.refuels, now)
        plan_text = ""
        if self.plan and self.plan.best:
            plan_text = f"Nächster Plan: {when_label(self.plan.best.start, now)}."
        title, text = weekly_message(summary, self.model.trend_label() if self.model else "–", plan_text)
        self._fire("woche", title, text, actions=False, extra={"summen": summary})

    def _send_plan(self, kind: str) -> None:
        now = self._now()
        pct, liters = self._fuel()
        title, text = plan_message(self.plan, self._ctx(now, pct, liters))
        self.notes["last_plan_sig"] = self._signature()
        self._fire(kind, title, text, actions=self.plan.status in ("muss", "jetzt", "heute"))
        self._save()

    def _fire(self, kind: str, title: str, text: str, actions: bool, extra: dict | None = None) -> None:
        plan = self.plan
        facts = {"art": kind, "titel": title, "text": text}
        if plan and plan.best:
            names = {e: m["name"] for e, m in self.stations.items()}
            facts.update({
                "status": plan.status,
                "empfohlene_tankstelle": names.get(plan.best.station),
                "empfohlener_zeitpunkt": when_label(plan.best.start, self._now()),
                "erwarteter_preis": round(plan.best.mu, 3),
                "langfristiger_preis": round(plan.p_lr, 3) if plan.p_lr else None,
                "vorteil_jetzt_eur": round(plan.now_advantage_eur, 2),
                "liter": round(plan.best.liters, 1),
                "preistrend": self.model.trend_label() if self.model else None,
            })
        facts.update(extra or {})
        self.log(f"Meldung [{kind}] {title}: {text}")
        self.fire_event(EVENT_NOTIFY, kind=kind, title=title, message=text,
                        actions=actions, facts=json.dumps(facts, ensure_ascii=False, default=str))

    # ============================================================== Tanken
    def _handle_refuel(self, liters: float, now: datetime, prev_time: str | None) -> None:
        done = self.notes.get("done")
        if done and now - datetime.fromisoformat(done) < timedelta(hours=12):
            when = datetime.fromisoformat(done)
            station = self.notes.get("done_station")
            source = "bestaetigt"
        else:
            start = datetime.fromisoformat(prev_time) if prev_time else now - timedelta(hours=6)
            start = max(start, now - timedelta(hours=24))
            when = start + (now - start) / 2
            if not (self.hours[0] <= when.hour < self.hours[1]):
                when = now
            station = self.plan.best.station if self.plan and self.plan.best else None
            source = "geschaetzt"
        if station not in self.stations:
            station = min(self.stations, key=lambda e: (self.history.price_at(e, when) or 9)
                          - self.discounts.euro(self.stations[e]["brand"], when.date()),
                          default=None)
        if station is None:
            return
        since = datetime.fromisoformat(self.refuels[-1]["time"]) if self.refuels else None
        refuel = evaluate_refuel(
            history=self.history, discounts=self.discounts,
            brands={e: m["brand"] for e, m in self.stations.items()},
            names={e: m["name"] for e, m in self.stations.items()},
            station=station, when=when, liters=liters, since=since, hours=self.hours,
            source=source).to_dict()
        self.refuels.append(refuel)
        self.notes.pop("done", None)
        self.notes["refueled"] = now.isoformat()
        self.notes.pop("reminder_for", None)
        self._cancel(self._reminder)
        if self.notify_refuel:
            title, text = refuel_message(refuel)
            self._fire("tankung", title, text, actions=False, extra={"tankung": refuel})

    # ============================================================== Helfer
    def _cancel(self, handle) -> None:
        if handle:
            try:
                self.cancel_timer(handle)
            except Exception:  # noqa: BLE001
                pass

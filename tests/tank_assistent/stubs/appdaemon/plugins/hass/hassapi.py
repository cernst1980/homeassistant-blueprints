"""Minimaler AppDaemon-Stub für Tests (nur die genutzten Methoden)."""

from datetime import datetime


class Hass:
    def __init__(self, args: dict, states: dict, now: datetime):
        self.args = args
        self.states = states
        self.now = now
        self.published: dict[str, str] = {}
        self.events: list[tuple[str, dict]] = []
        self.timers: list[tuple] = []
        self.logs: list[str] = []

    # Zeit
    def get_now(self):
        return self.now

    # Zustand
    def get_state(self, entity_id=None, attribute=None):
        if entity_id in ("sensor", "binary_sensor"):
            return {k: v for k, v in self.states.items() if k.startswith(entity_id + ".")}
        st = self.states.get(entity_id)
        if st is None:
            return None
        if attribute == "all":
            return st
        if attribute:
            return st.get("attributes", {}).get(attribute)
        return st.get("state")

    def listen_state(self, cb, entity_id, **kwargs):
        return ("state", entity_id)

    def listen_event(self, cb, event, **kwargs):
        return ("event", event)

    # Timer
    def run_every(self, cb, start, interval, **kwargs):
        self.timers.append(("every", cb, start, interval))
        return len(self.timers)

    def run_daily(self, cb, start, **kwargs):
        self.timers.append(("daily", cb, start))
        return len(self.timers)

    def run_in(self, cb, delay, **kwargs):
        self.timers.append(("in", cb, delay, kwargs))
        return len(self.timers)

    def run_at(self, cb, when, **kwargs):
        entry = ("at", cb, when, kwargs)
        self.timers.append(entry)
        return entry

    def cancel_timer(self, handle):
        if handle in self.timers:
            self.timers.remove(handle)

    # Aktionen
    def call_service(self, service, **kwargs):
        if service == "mqtt/publish":
            self.published[kwargs["topic"]] = kwargs["payload"]

    def fire_event(self, event, **kwargs):
        self.events.append((event, kwargs))

    def log(self, msg, level="INFO"):
        self.logs.append(f"{level}: {msg}")

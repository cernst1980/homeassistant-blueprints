"""Kleiner HA-Nachbau, um die Lüftungs-Blueprints ohne Home Assistant zu testen.

Rendert die Jinja-Templates der Blueprints mit HA-ähnlichen Funktionen (states, state_attr,
expand, today_at, …) und einer simulierten Uhr. Kein Ersatz für einen Test in HA, aber
gut genug, um Logikfehler bei Änderungen früh zu finden.
"""

from __future__ import annotations

import ast
import datetime as dt
import math
import os
import re

import jinja2
import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STATUS_BP = os.path.join(ROOT, "blueprints", "template", "lueftung", "lueftungsstatus_raum.yaml")
NOTIFY_BP = os.path.join(ROOT, "blueprints", "automation", "lueftung", "lueftung_benachrichtigung.yaml")


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!input", lambda loader, node: ("INPUT", loader.construct_scalar(node)))


def load_blueprint(path):
    with open(path, encoding="utf-8") as f:
        return yaml.load(f, Loader=_Loader)


def defaults(bp):
    out = {}

    def walk(d):
        for k, v in d.items():
            if isinstance(v.get("input"), dict):
                walk(v["input"])
            else:
                out[k] = v.get("default")

    walk(bp["blueprint"]["input"])
    return out


def parse(text):
    """Wie HA: gerenderte Templates werden in native Typen zurückverwandelt."""
    if not isinstance(text, str):
        return text
    t = text.strip()
    try:
        return ast.literal_eval(t)
    except Exception:
        return t


class _Obj:
    pass


class World:
    """Zustände, Attribute, Geräte und eine Uhr."""

    def __init__(self, start=dt.datetime(2026, 1, 1, 8, 0)):
        self.now = int(start.timestamp())
        self.states = {}   # entity -> {'state','attrs','lu','lc'}
        self.devices = {}  # device_id -> [entities]

    # ---- Zustände ----
    def set(self, entity, state, attrs=None, changed=None):
        old = self.states.get(entity)
        state = str(state)
        lc = changed if changed is not None else (
            self.now if (not old or old["state"] != state) else old["lc"])
        self.states[entity] = {"state": state, "attrs": dict(attrs or (old["attrs"] if old else {})),
                               "lu": self.now, "lc": lc}

    def obj(self, entity):
        d = self.states[entity]
        o = _Obj()
        o.entity_id = entity
        o.state = d["state"]
        o.name = d["attrs"].get("friendly_name", entity)
        o.attributes = d["attrs"]
        o.last_changed = dt.datetime.fromtimestamp(d["lc"])
        o.last_updated = o.last_reported = dt.datetime.fromtimestamp(d["lu"])
        return o

    # ---- Jinja-Umgebung (einmal pro Welt, Templates werden zwischengespeichert) ----
    def env(self):
        if getattr(self, "_env", None) is not None:
            return self._env
        env = jinja2.Environment(extensions=["jinja2.ext.loopcontrols"])
        w = self

        def states(e):
            return w.states[e]["state"] if e in w.states else "unknown"

        def state_attr(e, k):
            return w.states[e]["attrs"].get(k) if e in w.states else None

        def is_state(e, v):
            return states(e) in v if isinstance(v, (list, tuple)) else states(e) == v

        def expand(x):
            items = [x] if isinstance(x, str) else list(x or [])
            return [w.obj(e) for e in items if e in w.states]

        def as_timestamp(x, default=None):
            if hasattr(x, "timestamp"):
                return x.timestamp()
            try:
                return float(x)
            except Exception:
                return default

        env.tests["is_state"] = is_state
        env.tests["is_state_attr"] = lambda e, k, v: state_attr(e, k) == v
        env.tests["match"] = lambda v, p: re.match(p, v) is not None
        env.filters["timestamp_custom"] = lambda ts, fmt="%Y-%m-%d %H:%M:%S", local=True: \
            dt.datetime.fromtimestamp(float(ts)).strftime(fmt)
        env.filters["slugify"] = lambda x: re.sub(r"[^a-z0-9]+", "_", str(x).lower()).strip("_")
        env.globals.update(
            states=states, state_attr=state_attr, is_state=is_state, expand=expand,
            device_id=lambda e: next((d for d, l in w.devices.items() if e in l), None),
            device_entities=lambda d: w.devices.get(d, []),
            device_attr=lambda d, k: d,
            today_at=lambda t: dt.datetime.combine(dt.datetime.fromtimestamp(w.now).date(),
                                                   dt.time.fromisoformat(str(t))),
            as_timestamp=as_timestamp,
            now=lambda: dt.datetime.fromtimestamp(w.now), timedelta=dt.timedelta, e=math.e, none=None)
        self._env = env
        self._cache = {}
        return env

    def render(self, env, tpl, ctx):
        if isinstance(tpl, str) and ("{{" in tpl or "{%" in tpl):
            t = self._cache.get(tpl)
            if t is None:
                t = self._cache[tpl] = env.from_string(tpl)
            return parse(t.render(**ctx))
        return tpl


class StatusZone:
    """Ein Lüftungsstatus-Sensor (Template-Blueprint) in der simulierten Welt."""

    def __init__(self, world, entity="sensor.luftung_test", **inputs):
        self.w = world
        self.entity = entity
        self.bp = load_blueprint(STATUS_BP)
        self.inputs = defaults(self.bp)
        self.inputs.update(raum="Test", temp_innen="sensor.t_in", feuchte_innen="sensor.rh_in", co2="",
                           fenster="binary_sensor.win", temp_aussen="sensor.t_out",
                           feuchte_aussen="sensor.rh_out", wand_temp="", tmax_heute="")
        self.inputs.update(inputs)

    def run(self):
        env = self.w.env()
        this = _Obj()
        this.entity_id = self.entity
        ctx = {"this": this}
        for step in self.bp["actions"]:
            for k, v in step["variables"].items():
                if isinstance(v, tuple):
                    v = self.inputs[v[1]]
                ctx[k] = self.w.render(env, v, ctx)
        attrs = {k: self.w.render(env, v, ctx) for k, v in self.bp["sensor"]["attributes"].items()}
        state = str(self.w.render(env, self.bp["sensor"]["state"], ctx))
        self.w.set(self.entity, state, attrs)
        return state, attrs

    def step(self, minutes=1, **values):
        """Uhr weiterdrehen und Messwerte setzen (Schlüssel: sensor__t_in=21)."""
        state = attrs = None
        for _ in range(max(1, int(minutes))):
            self.w.now += 60
            for k, v in values.items():
                self.w.set(k.replace("__", "."), v)
            state, attrs = self.run()
        return state, attrs

    def jump(self, minutes, **values):
        """Größerer Zeitsprung mit nur einer Auswertung."""
        self.w.now += int(minutes * 60) - 60
        return self.step(1, **values)


class Notify:
    """Rendert Variablen und Zweige der Benachrichtigungs-Automation."""

    def __init__(self, world, sensors, **inputs):
        self.w = world
        self.bp = load_blueprint(NOTIFY_BP)
        self.inputs = defaults(self.bp)
        self.inputs.update(sensoren=sensors, geraete=["handy"], wetter=["weather.home"])
        self.inputs.update(inputs)
        world.set("zone.home", "1")
        if "weather.home" not in world.states:
            world.set("weather.home", "cloudy")

    def context(self, trigger=None):
        env = self.w.env()
        ctx = {"trigger": trigger}
        for k, v in self.bp["variables"].items():
            if isinstance(v, tuple):
                v = self.inputs[v[1]]
            ctx[k] = self.w.render(env, v, ctx)
        return env, ctx

    def choose(self):
        return next(a["choose"] for a in self.bp["actions"] if "choose" in a)

    def close_block(self):
        """Oberster if-Block „Fenster schließen“ (zustandslos)."""
        return next(a for a in self.bp["actions"] if "if" in a)

    def branch(self, trigger_id):
        for b in self.choose():
            ids = b["conditions"][0].get("id")
            ids = ids if isinstance(ids, list) else [ids]
            if trigger_id in ids:
                return b
        raise KeyError(trigger_id)

    def variables(self, block, env, ctx):
        for k, v in block["variables"].items():
            ctx[k] = self.w.render(env, v, ctx)
        return ctx


def trigger(entity, from_state=None, to_state=None, from_attrs=None, to_attrs=None, tid=None, changed=None):
    t = {"entity_id": entity, "id": tid}
    fs = _Obj()
    fs.state = from_state
    fs.attributes = from_attrs or {}
    fs.last_changed = dt.datetime.fromtimestamp(changed) if changed else dt.datetime.now()
    ts = _Obj()
    ts.state = to_state
    ts.attributes = to_attrs or {}
    ts.last_changed = dt.datetime.now()
    t["from_state"], t["to_state"] = fs, ts
    return t

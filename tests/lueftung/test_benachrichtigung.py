"""Logik der Benachrichtigungs-Automation: Raumlisten, Grundlüftung, gesammelte Bestätigung."""

import datetime as dt

from ha_sim import Notify, World, trigger

NOW = dt.datetime(2026, 10, 11, 14, 0)
SENSOREN = ["sensor.buero", "sensor.wc", "sensor.kino", "sensor.bad"]


def welt():
    return World(NOW)


def zone(w, e, state, grund="", seit_min=60, **attrs):
    a = {"raum": e.split(".")[1].upper(), "grund": grund}
    a.update(attrs)
    w.set(e, state, a, changed=w.now - seit_min * 60)


def ts(w, minuten):
    return int(w.now - minuten * 60)


def test_grundlueftung_nur_mitnehmen():
    w = welt()
    zone(w, "sensor.buero", "lueften", "CO₂ 1300 ppm", 15)
    zone(w, "sensor.wc", "ok", "Grundlüftung fällig, seit 30 h nicht gelüftet", grundlueftung_faellig=True)
    zone(w, "sensor.kino", "ok")
    zone(w, "sensor.bad", "ok")
    n = Notify(w, SENSOREN)
    _, c = n.context()
    assert c["bedarf"]["liste"] == ["BUERO: CO₂ 1300 ppm"]
    assert c["bedarf"]["mit"] == ["WC"]
    assert "Bei der Gelegenheit auch: WC" in c["bedarf_text"]


def test_nur_grundlueftung_keine_meldung():
    w = welt()
    zone(w, "sensor.buero", "ok")
    zone(w, "sensor.wc", "ok", "Grundlüftung fällig", grundlueftung_faellig=True)
    zone(w, "sensor.kino", "ok")
    zone(w, "sensor.bad", "ok")
    _, c = Notify(w, SENSOREN).context()
    assert c["bedarf"]["liste"] == [] and c["bedarf"]["mit"] == ["WC"]


def test_grundlueftung_nicht_bei_regen():
    w = welt()
    w.set("weather.home", "rainy")
    zone(w, "sensor.buero", "lueften", "CO₂ 1300 ppm", 15)
    zone(w, "sensor.wc", "ok", "Grundlüftung fällig", grundlueftung_faellig=True)
    zone(w, "sensor.kino", "ok")
    zone(w, "sensor.bad", "ok")
    _, c = Notify(w, SENSOREN).context()
    assert c["bedarf"]["mit"] == [] and "Regen" in c["bedarf_text"]


def _bestaetigung(n, entity, eigen_ts):
    """Simuliert den Zweig „befolgt“ nach der Wartezeit; liefert (Aktion, Titel, Text)."""
    b = n.branch("befolgt")
    t = trigger(entity, tid="befolgt", from_attrs={"erledigt_ts": None}, to_attrs={"erledigt_ts": eigen_ts})
    env, c = n.context(t)
    seq = b["sequence"]
    n.variables(seq[0], env, c)
    n.variables(seq[2], env, c)
    if n.w.render(env, seq[3]["value_template"], c) is not True:
        return ("nicht_letzter", None, None)
    if c["gemeldet"] is not True:
        return ("aufraeumen" if n.w.render(env, seq[4]["then"][0]["if"], c) is True else "nichts", None, None)
    n.variables(seq[4]["else"][0], env, c)
    return ("senden", c["titel"], c["text"])


def test_runde_mehrere_fenster_eine_bestaetigung():
    w = welt()
    zone(w, "sensor.buero", "offen", erledigt_ts=ts(w, 9), erledigt_min=15, erledigt_grund="CO₂ 1300 ppm")
    zone(w, "sensor.wc", "offen", erledigt_ts=ts(w, 7), erledigt_min=600, erledigt_grund="Grundlüftung fällig")
    zone(w, "sensor.kino", "offen", erledigt_ts=ts(w, 5), erledigt_min=900, erledigt_grund="Grundlüftung fällig")
    zone(w, "sensor.bad", "ok")
    n = Notify(w, SENSOREN)
    assert _bestaetigung(n, "sensor.buero", ts(w, 9))[0] == "nicht_letzter"
    assert _bestaetigung(n, "sensor.wc", ts(w, 7))[0] == "nicht_letzter"
    aktion, titel, text = _bestaetigung(n, "sensor.kino", ts(w, 5))
    assert aktion == "senden" and titel == "✅ Gelüftet"
    assert text.startswith("✅ BUERO, WC, KINO")


def test_vergessener_raum_wird_genannt():
    w = welt()
    zone(w, "sensor.buero", "offen", erledigt_ts=ts(w, 5), erledigt_min=15, erledigt_grund="CO₂ 1300 ppm")
    zone(w, "sensor.bad", "lueften", "Feuchte, Wand 82 % rF", 30)
    zone(w, "sensor.wc", "lueften", "Feuchte, Wand 80 % rF", 2)     # zu frisch → eigene Meldung später
    zone(w, "sensor.kino", "ok", "Grundlüftung fällig", grundlueftung_faellig=True)
    aktion, titel, text = _bestaetigung(Notify(w, SENSOREN), "sensor.buero", ts(w, 5))
    assert aktion == "senden" and titel == "🪟 Noch zu lüften"
    assert "BAD: Feuchte" in text and "WC:" not in text and "Bei der Gelegenheit auch: KINO" in text


def test_nicht_gemeldet_keine_bestaetigung():
    w = welt()
    zone(w, "sensor.buero", "offen", erledigt_ts=ts(w, 5), erledigt_min=3, erledigt_grund="CO₂ 1250 ppm")
    for e in ("sensor.wc", "sensor.kino", "sensor.bad"):
        zone(w, e, "ok")
    assert _bestaetigung(Notify(w, SENSOREN), "sensor.buero", ts(w, 5))[0] == "aufraeumen"


def test_gleichzeitig_geoeffnet_nur_eine_meldung():
    w = welt()
    zone(w, "sensor.buero", "offen", erledigt_ts=ts(w, 5), erledigt_min=15, erledigt_grund="CO₂")
    zone(w, "sensor.wc", "offen", erledigt_ts=ts(w, 5), erledigt_min=15, erledigt_grund="Feuchte")
    zone(w, "sensor.kino", "ok")
    zone(w, "sensor.bad", "ok")
    n = Notify(w, SENSOREN)
    ergebnisse = [_bestaetigung(n, e, ts(w, 5))[0] for e in ("sensor.buero", "sensor.wc")]
    assert sorted(ergebnisse) == ["nicht_letzter", "senden"]


def test_erledigt_tags():
    w = welt()
    for e in SENSOREN:
        zone(w, e, "ok")
    n = Notify(w, SENSOREN)
    b = n.branch("erledigt")

    def tags(von, nach):
        t = trigger("sensor.buero", von, nach, tid="erledigt")
        env, c = n.context(t)
        n.variables(b["sequence"][0], env, c)
        # lueftung_wetter wird ohnehin entfernt, wenn kein Fenster offen ist
        return [x for x in c["tags"] if x != "lueftung_wetter"], c["geschlossen_ok"]

    assert tags("lueften", "ok") == (["lueftung_schliessen_sensor_buero", "lueftung_bedarf"], False)
    assert tags("lueften", "offen") == (["lueftung_schliessen_sensor_buero"], False)
    assert tags("lueften", "schliessen") == ([], False)
    assert tags("schliessen", "ok") == ([], True)

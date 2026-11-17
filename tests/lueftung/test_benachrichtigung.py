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
    n.variables(seq[4], env, c)
    if c["gemeldet"] is not True and len(c["noch"]["l"]) == 0:
        return ("aufraeumen", None, None)
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
    assert aktion == "senden" and titel == "✅ Lüften begonnen"
    assert text.startswith("✅ Fenster geöffnet: BUERO, WC, KINO")


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


def test_erledigt_tags_und_schliessen_liste():
    w = welt()
    zone(w, "sensor.buero", "ok")
    zone(w, "sensor.wc", "schliessen", "seit 12 Min. offen", 5)
    zone(w, "sensor.kino", "ok")
    zone(w, "sensor.bad", "ok")
    n = Notify(w, SENSOREN)
    b = n.branch("erledigt")

    def lauf(von, nach, seit_s=300):
        t = trigger("sensor.buero", von, nach, tid="erledigt", changed=w.now - seit_s)
        env, c = n.context(t)
        n.variables(b["sequence"][0], env, c)
        tags = [x for x in c["tags"] if x not in ("lueftung_wetter", "lueftung_nacht")]
        text = None
        if n.w.render(env, b["sequence"][2]["if"], c) is True:
            n.variables(b["sequence"][2]["then"][0], env, c)
            text = c["text"]
        return tags, text

    assert lauf("lueften", "ok")[0] == ["lueftung_bedarf"]
    assert lauf("lueften", "offen")[0] == []
    # Büro geschlossen, WC noch offen → Liste still aktualisieren
    tags, text = lauf("schliessen", "ok")
    assert tags == [] and text.startswith("✅ BUERO geschlossen") and "Noch offen:\nWC: seit 12 Min." in text
    # Grund weggefallen, Fenster aber offen → kein ✅
    tags, text = lauf("schliessen", "offen")
    assert "✅" not in text and "WC:" in text
    # Meldung war noch gar nicht raus (< 100 s) → nichts senden
    assert lauf("schliessen", "ok", seit_s=30)[1] is None
    # letzter Raum geschlossen → ✅ ersetzt die Nachricht
    zone(w, "sensor.wc", "ok")
    tags, text = lauf("schliessen", "ok")
    assert tags == [] and text.startswith("✅ BUERO geschlossen") and "Noch offen" not in text
    tags, text = lauf("schliessen", "offen")
    assert tags == ["lueftung_schliessen"] and text is None


def _schliessen(n, tid, mein_ts=None):
    """Oberer Block „Fenster schließen“: (senden?, titel, text)."""
    blk = n.close_block()["then"]
    t = {"id": tid, "entity_id": "sensor.wc"}
    env, c = n.context(t)
    if mein_ts is not None:
        c["mein_ts"] = mein_ts
    n.variables(blk[1], env, c)
    if c["senden"] is not True:
        return False, None, None
    n.variables(blk[2]["then"][0], env, c)
    return True, c["titel"], c["text"]


def _zwei_offen(w):
    zone(w, "sensor.buero", "schliessen", "Luft ist ausgetauscht", 2)
    zone(w, "sensor.wc", "schliessen", "seit 10 Min. offen", 1)
    zone(w, "sensor.kino", "ok")
    zone(w, "sensor.bad", "ok", regengeschuetzt=True)


def test_schliessen_gesammelt():
    w = welt()
    _zwei_offen(w)
    w.set("weather.home", "rainy")
    n = Notify(w, SENSOREN)
    assert _schliessen(n, "schliessen", mein_ts=ts(w, 2))[0] is False     # neuerer Raum übernimmt
    ok, titel, text = _schliessen(n, "schliessen", mein_ts=ts(w, 1))
    assert ok and titel == "🪟 Fenster schließen (2)"
    assert text.splitlines()[:2] == ["BUERO: Luft ist ausgetauscht", "WC: seit 10 Min. offen"]
    assert "🌧 Es regnet" in text


def test_schliessen_erinnerung_wachsender_abstand():
    w = welt()
    gesendet = []
    for minute in range(0, 200, 5):
        w.now = int(NOW.timestamp()) + minute * 60
        zone(w, "sensor.buero", "schliessen", "seit X Min. offen", 0)
        w.states["sensor.buero"]["lc"] = int(NOW.timestamp()) - 90
        for e in ("sensor.wc", "sensor.kino", "sensor.bad"):
            zone(w, e, "ok")
        if _schliessen(Notify(w, SENSOREN), "erinnerung")[0]:
            gesendet.append(minute)
    assert gesendet == [10, 20, 40, 80, 140]       # danach jede Stunde


def test_schliessen_nicht_wenn_niemand_da_oder_ruhezeit():
    w = welt()
    _zwei_offen(w)
    w.devices["handy"] = ["device_tracker.handy"]
    w.set("device_tracker.handy", "not_home")
    assert _schliessen(Notify(w, SENSOREN), "nachholen")[0] is False
    w.set("device_tracker.handy", "home")
    assert _schliessen(Notify(w, SENSOREN), "nachholen")[0] is True
    w.now = int(dt.datetime(2026, 10, 11, 23, 0).timestamp())
    _zwei_offen(w)
    assert _schliessen(Notify(w, SENSOREN), "start")[0] is False
    assert _schliessen(Notify(w, SENSOREN, schliessen_nachts=True), "start")[0] is True


def test_lueften_erinnerung_wachsender_abstand():
    w = welt()
    for e in ("sensor.wc", "sensor.kino", "sensor.bad"):
        zone(w, e, "ok")
    start = int(NOW.timestamp())
    gesendet = []
    for minute in range(0, 300, 5):
        w.now = start + minute * 60
        zone(w, "sensor.buero", "lueften", "CO₂ 1300 ppm", 0)
        w.states["sensor.buero"]["lc"] = start - 10 * 60     # seit 10 Min. lueften = gemeldet bei 0
        _, c = Notify(w, SENSOREN).context()
        if c["lueften_faellig"] is True:
            gesendet.append(minute)
    assert gesendet == [30, 60, 120, 240]          # danach alle 4 h


def test_lueften_nur_stabile_raeume_und_kein_doppelversand():
    w = welt()
    zone(w, "sensor.buero", "lueften", "CO₂ 1300 ppm", 10)
    zone(w, "sensor.wc", "lueften", "Feuchte", 10)
    zone(w, "sensor.kino", "lueften", "Feuchte", 3)          # noch nicht stabil
    zone(w, "sensor.bad", "ok")
    n = Notify(w, SENSOREN)
    _, c = n.context()
    assert c["bedarf"]["liste"] == ["BUERO: CO₂ 1300 ppm", "WC: Feuchte"]
    b = n.lueften_block()

    def sendet(entity):
        t = trigger(entity, "ok", "lueften", tid="bedarf")
        env, c = n.context(t)
        return all(n.w.render(env, cond, c) is True for cond in b["if"][1:])

    assert [sendet("sensor.buero"), sendet("sensor.wc")] == [False, True]   # Gleichstand: größte ID


def test_zweiter_raum_kurz_danach_wird_gemeldet():
    w = welt()
    zone(w, "sensor.wc", "dringend", "Feuchtespitze", 0)
    w.states["sensor.wc"]["lc"] = w.now - 30                 # 30 s früher
    zone(w, "sensor.bad", "dringend", "Feuchtespitze", 0)    # jetzt
    zone(w, "sensor.buero", "ok")
    zone(w, "sensor.kino", "ok")
    n = Notify(w, SENSOREN)
    b = n.lueften_block()
    t = trigger("sensor.bad", "ok", "dringend", tid="bedarf")
    env, c = n.context(t)
    assert all(n.w.render(env, cond, c) is True for cond in b["if"][1:])
    assert len(c["bedarf"]["liste"]) == 2

def _bericht(n):
    b = n.branch("sensorbericht")
    env, c = n.context({"id": "sensorbericht", "entity_id": None})
    n.variables(b["sequence"][0], env, c)
    return c["bericht"]


def test_sensorbericht_meldet_schwache_batterie():
    w = welt()
    for e in SENSOREN:
        zone(w, e, "ok", batterien=[])
    zone(w, "sensor.bad", "ok", batterien=["sensor.bad_batterie"])
    w.set("sensor.bad_batterie", 9, {"friendly_name": "Bad Thermometer Batterie", "device_class": "battery"})
    assert "🔋 Bad Thermometer Batterie: 9 %" in _bericht(Notify(w, SENSOREN))


def _zwei_handys(w, fokus_chris="off", fokus_steffi="off"):
    w.devices["chris"] = ["device_tracker.chris", "binary_sensor.chris_focus"]
    w.devices["steffi"] = ["device_tracker.steffi", "binary_sensor.steffi_focus"]
    w.set("device_tracker.chris", "home")
    w.set("device_tracker.steffi", "home")
    w.set("binary_sensor.chris_focus", fokus_chris)
    w.set("binary_sensor.steffi_focus", fokus_steffi)
    return dict(geraete=["chris", "steffi"], schlaf_entitaeten=["binary_sensor.chris_focus", "binary_sensor.steffi_focus"])


def test_schlafmodus_pro_person():
    w = World(dt.datetime(2026, 10, 30, 23, 0))
    for e in SENSOREN:
        zone(w, e, "ok")
    _, c = Notify(w, SENSOREN, **_zwei_handys(w, fokus_chris="on")).context()
    assert c["ziele_wach"] == ["notify.mobile_app_steffi"] and c["ruhezeit"] is False
    _, c = Notify(w, SENSOREN, **_zwei_handys(w, "on", "on")).context()
    assert c["ziele_wach"] == [] and c["ruhezeit"] is True
    # Fokus tagsüber (Arbeiten) ist kein Schlaf
    w.now = int(dt.datetime(2026, 10, 30, 14, 0).timestamp())
    _, c = Notify(w, SENSOREN, **_zwei_handys(w, "on", "on")).context()
    assert len(c["ziele_wach"]) == 2 and c["ruhezeit"] is False


def test_feste_ruhezeit_ohne_schlafmodus():
    w = World(dt.datetime(2026, 10, 30, 23, 0))
    for e in SENSOREN:
        zone(w, e, "ok")
    _, c = Notify(w, SENSOREN).context()
    assert c["ruhezeit"] is True and c["ziele_wach"] == []
    w.now = int(dt.datetime(2026, 10, 30, 8, 0).timestamp())
    _, c = Notify(w, SENSOREN).context()
    assert c["ruhezeit"] is False


def test_gute_nacht_check():
    w = World(dt.datetime(2026, 10, 30, 22, 30))
    zone(w, "sensor.buero", "offen")
    zone(w, "sensor.wc", "ok")
    zone(w, "sensor.kino", "ok")
    zone(w, "sensor.bad", "offen", nacht=True)        # z. B. Schlafzimmer mit Nachtlüftung
    inputs = _zwei_handys(w)
    n = Notify(w, SENSOREN, **inputs)
    b = n.branch("gute_nacht")
    w.set("binary_sensor.chris_focus", "on")
    t = trigger("binary_sensor.chris_focus", "off", "on", tid="gute_nacht")
    t["platform"] = "state"
    env, c = n.context(t)
    assert c["offen_nachts"] == ["BUERO"]
    assert all(n.w.render(env, cond, c) is True for cond in b["conditions"][1:])
    n.variables(b["sequence"][0], env, c)
    assert c["empfaenger"] == ["notify.mobile_app_chris"]
    # feste Uhrzeit zählt nur ohne Schlafmodus
    t2 = {"id": "gute_nacht", "platform": "time", "entity_id": None}
    env, c = n.context(t2)
    assert n.w.render(env, b["conditions"][2], c) is False


def test_erinnerung_pro_raum_nicht_vom_alten_bedarf_blockiert():
    w = welt()
    start = int(NOW.timestamp())
    for e in ("sensor.wc", "sensor.kino"):
        zone(w, e, "ok")
    zone(w, "sensor.bad", "lueften", "Feuchte", 26 * 60 + 7)       # hängt seit 26 h
    gesendet = []
    for minute in range(0, 130, 5):
        w.now = start + minute * 60
        zone(w, "sensor.buero", "dringend", "CO₂ 3000 ppm", 0)
        w.states["sensor.buero"]["lc"] = start
        _, c = Notify(w, SENSOREN).context()
        if c["lueften_faellig"] is True:
            gesendet.append(minute)
    assert [m for m in gesendet if m in (15, 30, 60, 120)] == [15, 30, 60, 120]


def test_weboberflaeche_auch_ohne_handy():
    w = welt()
    zone(w, "sensor.buero", "lueften", "CO₂ 1300 ppm", 15)
    zone(w, "sensor.wc", "schliessen", "seit 12 Min. offen", 5)
    zone(w, "sensor.kino", "ok")
    zone(w, "sensor.bad", "ok")
    w.devices["handy"] = ["device_tracker.handy"]
    w.set("device_tracker.handy", "not_home")
    n = Notify(w, SENSOREN)
    blk = n.web_block()
    env, c = n.context({"id": "bedarf", "entity_id": "sensor.buero"})
    assert all(n.w.render(env, x, c) is not False for x in blk["if"] if isinstance(x, str))
    n.variables(blk["then"][0], env, c)
    assert c["web_lueften"] == "BUERO: CO₂ 1300 ppm" and c["web_schliessen"] == "WC: seit 12 Min. offen"
    assert c["ziele_da"] == []


def test_heimkommen_nur_an_die_ankommende_person():
    w = welt()
    for e in SENSOREN:
        zone(w, e, "ok")
    w.devices["chris"] = ["device_tracker.chris"]
    w.devices["steffi"] = ["device_tracker.steffi"]
    w.set("device_tracker.chris", "home", changed=w.now - 3 * 3600)
    w.set("device_tracker.steffi", "home", changed=w.now - 5 * 60 - 10)
    t = trigger("zone.home", "1", "2", tid="ankunft")
    _, c = Notify(w, SENSOREN, geraete=["chris", "steffi"]).context(t)
    assert c["ankommende"] == ["notify.mobile_app_steffi"] and c["nachhol_ziele"] == ["notify.mobile_app_steffi"]
    # Neustart / jemand geht: keine Ankunft
    t = trigger("zone.home", "2", "1", tid="ankunft")
    _, c = Notify(w, SENSOREN, geraete=["chris", "steffi"]).context(t)
    assert c["ankommende"] == []


def test_geloeschtes_handy_wird_uebersprungen():
    w = welt()
    for e in SENSOREN:
        zone(w, e, "ok")
    w.devices["chris"] = ["device_tracker.chris"]
    w.set("device_tracker.chris", "home")
    n = Notify(w, SENSOREN, geraete=["chris", "alte_device_id"])
    _, c = n.context()
    assert c["ziele_alle"] == ["notify.mobile_app_chris"]
    assert any("existiert nicht mehr" in x for x in _bericht(n))


# ---------- Amtliche Warnungen (DWD / NINA) ----------

DWD = "sensor.dwd_warnstufe"
NINA1 = "binary_sensor.region_warnung_1"


def dwd_attrs(*warnungen):
    a = {"warning_count": len(warnungen)}
    for i, (name, stufe, start) in enumerate(warnungen, 1):
        a[f"warning_{i}_name"] = name
        a[f"warning_{i}_level"] = stufe
        a[f"warning_{i}_start"] = start
        a[f"warning_{i}_headline"] = f"Amtliche WARNUNG vor {name}"
        a[f"warning_{i}_end"] = NOW + dt.timedelta(hours=10)
    return a


def warn_ctx(w, from_attrs, to_attrs, **inputs):
    inputs.setdefault('warn_dwd_stufe', 2)
    n = Notify(w, SENSOREN, warn_dwd=[DWD], **inputs)
    t = trigger(DWD, "2", "2", from_attrs, to_attrs, tid="warnung")
    _, c = n.context(t)
    return c


def test_dwd_neue_warnung_wird_gemeldet():
    w = welt()
    zone(w, "sensor.buero", "ok")
    alt = dwd_attrs()
    neu = dwd_attrs(("FROST", 2, "2026-10-12T00:00"))
    c = warn_ctx(w, alt, neu)
    assert [x["name"] for x in c["warn_neu"]] == ["FROST"]
    assert c["warn_neu"][0]["art"] == "frost"


def test_dwd_bekannte_warnung_nicht_doppelt():
    w = welt()
    a = dwd_attrs(("STARKREGEN", 2, "2026-10-12T00:00"))
    c = warn_ctx(w, a, dict(a, last_update="x"))
    assert c["warn_neu"] == []


def test_dwd_unter_stufe_und_fremdes_stichwort_ignoriert():
    w = welt()
    neu = dwd_attrs(("FROST", 1, "a"), ("NEBEL", 3, "b"))
    c = warn_ctx(w, dwd_attrs(), neu)
    assert c["warn_neu"] == []


def test_dwd_sturm_ist_wind_und_stufe_regelt_empfaenger():
    w = welt()
    neu = dwd_attrs(("STURMBÖEN", 3, "a"))
    c = warn_ctx(w, dwd_attrs(), neu)
    assert c["warn_neu"][0]["art"] == "wind"
    assert c["warn_neu"][0]["stufe"] == 3


def test_nina_schwere_warnung_mit_fenster_hinweis():
    w = welt()
    w.set(NINA1, "on", {"id": "mowas.123", "description": "Bitte Fenster und Türen schließen."})
    w.set("sensor.region_schweregrad_1", "severe")
    w.set("sensor.region_uberschrift_1", "Brand: Rauchentwicklung")
    n = Notify(w, SENSOREN, warn_nina=[NINA1])
    _, c = n.context(trigger(NINA1, "off", "on", tid="warnung"))
    assert len(c["warn_neu"]) == 1
    assert c["warn_neu"][0]["art"] == "fenster"
    assert c["warn_neu"][0]["quelle"] == "nina"


def test_nina_leichte_und_dwd_dopplung_ignoriert():
    w = welt()
    w.set(NINA1, "on", {"id": "dwd.2.49.0"})
    w.set("sensor.region_schweregrad_1", "severe")
    w.set("sensor.region_uberschrift_1", "Amtliche WARNUNG vor STURMBÖEN")
    n = Notify(w, SENSOREN, warn_nina=[NINA1], warn_dwd=[DWD])
    _, c = n.context(trigger(NINA1, "off", "on", tid="warnung"))
    assert c["warn_neu"] == []
    w.set(NINA1, "on", {"id": "mowas.1"})
    w.set("sensor.region_schweregrad_1", "moderate")
    _, c = n.context(trigger(NINA1, "off", "on", tid="warnung"))
    assert c["warn_neu"] == []


def test_warnung_ohne_offene_fenster_keine_push():
    w = welt()
    zone(w, "sensor.buero", "ok")
    n = Notify(w, SENSOREN, warn_dwd=[DWD], warn_dwd_stufe=2)
    env, c = n.context(trigger(DWD, "2", "2", dwd_attrs(), dwd_attrs(("FROST", 2, "a")), tid="warnung"))
    b = next(x for x in n.choose() if "warn_neu" in str(x["conditions"]))
    rep = next(a for a in b["sequence"] if "repeat" in a)["repeat"]["for_each"]
    assert n.w.render(env, rep, c) == []
    zone(w, "sensor.buero", "offen")
    env, c = n.context(trigger(DWD, "2", "2", dwd_attrs(), dwd_attrs(("FROST", 2, "a")), tid="warnung"))
    assert len(n.w.render(env, rep, c)) == 1

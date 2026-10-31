"""Szenarien für den Lüftungsstatus pro Raum (Template-Blueprint)."""

import datetime as dt

from ha_sim import StatusZone, World

AUSSEN_WINTER = dict(sensor__t_out=8, sensor__rh_out=80)


def zone(start=dt.datetime(2026, 1, 1, 8, 0), **inputs):
    return StatusZone(World(start), **inputs)


def test_co2_lueften_und_plateau():
    z = zone(co2="sensor.co2")
    w = dict(sensor__t_in=21, sensor__rh_in=50, **AUSSEN_WINTER)
    s, a = z.step(3, binary_sensor__win="off", sensor__co2=900, **w)
    assert s == "ok"
    s, a = z.step(2, binary_sensor__win="off", sensor__co2=1300, **w)
    assert s == "lueften" and a["grund"].startswith("CO₂ 1300")
    # Öffnen: CO₂ fällt, dann Plateau → schließen
    z.step(1, binary_sensor__win="on", sensor__co2=1250, **w)
    for c in (1100, 950, 850, 800, 790, 785, 783):
        s, a = z.step(1, binary_sensor__win="on", sensor__co2=c, **w)
    assert s == "schliessen"
    assert a["erledigt_ts"] is not None and a["erledigt_grund"].startswith("CO₂")
    s, a = z.step(1, binary_sensor__win="off", sensor__co2=783, **w)
    assert s == "ok"


def test_maximaldauer_winter_und_aktualisierter_grund():
    z = zone()
    w = dict(sensor__t_in=20.5, sensor__rh_in=62, sensor__t_out=16.1, sensor__rh_out=85)
    z.step(3, binary_sensor__win="off", **w)
    s, a = z.step(20, binary_sensor__win="on", **w)
    assert s == "schliessen" and "Min. offen" in a["grund"]
    vorher = int(a["grund"].split("seit ")[1].split(" ")[0])
    s, a = z.step(30, binary_sensor__win="on", **w)
    assert int(a["grund"].split("seit ")[1].split(" ")[0]) == vorher + 30   # Grund wird laufend aktualisiert


def test_grundlueftung_ist_nur_hinweis():
    z = zone(grundlueftung_h=24)
    w = dict(sensor__t_in=21, sensor__rh_in=50, sensor__t_out=10, sensor__rh_out=70)
    z.step(1, binary_sensor__win="off", **w)
    s, a = z.jump(24 * 60 + 10, binary_sensor__win="off", **w)
    assert s == "ok"
    assert a["grundlueftung_faellig"] is True and a["grund"].startswith("Grundlüftung fällig")
    # kurzer Durchgang zählt nicht
    z.step(1, binary_sensor__win="on", **w)
    s, a = z.step(1, binary_sensor__win="off", **w)
    assert a["grundlueftung_faellig"] is True and a["erledigt_ts"] is None
    # 4 Min. offen: erledigt
    s, a = z.step(4, binary_sensor__win="on", **w)
    assert a["erledigt_grund"] == "Grundlüftung fällig"
    s, a = z.step(1, binary_sensor__win="off", **w)
    assert a["grundlueftung_faellig"] is False


def test_grundlueftung_nicht_bei_feuchter_aussenluft():
    z = zone(grundlueftung_h=8)
    z.step(1, binary_sensor__win="off", sensor__t_in=21, sensor__rh_in=50, sensor__t_out=20, sensor__rh_out=85)
    s, a = z.jump(10 * 60, binary_sensor__win="off", sensor__t_in=21, sensor__rh_in=50,
                  sensor__t_out=20, sensor__rh_out=85)
    assert a["grundlueftung_faellig"] is False


def test_dauerlueften_buero_zu_kalt_und_kippen():
    z = zone(start=dt.datetime(2026, 5, 1, 9, 0), dauerlueften="immer", nacht_min_temp=19,
             dauer_ab_aussen=16, co2="sensor.co2")
    w = dict(sensor__t_out=17, sensor__rh_out=60, sensor__rh_in=50, sensor__co2=700)
    z.step(3, binary_sensor__win="off", sensor__t_in=21.5, **w)
    s, a = z.step(25, binary_sensor__win="on", sensor__t_in=21.5, **w)
    assert s == "offen"
    s, a = z.jump(15, binary_sensor__win="on", sensor__t_in=18.9, **w)
    assert s == "schliessen" and a["grund"].startswith("Raum zu kalt")
    s, a = z.jump(15, binary_sensor__win="on", sensor__t_in=19.4, **w)
    assert s == "schliessen"            # Hysterese
    s, a = z.jump(15, binary_sensor__win="on", sensor__t_in=19.6, **w)
    assert s == "offen"                 # gekippt, Raum erholt sich → Meldung weg


def test_dauerlueften_unter_aussengrenze_gelten_stossregeln():
    z = zone(start=dt.datetime(2026, 5, 1, 9, 0), dauerlueften="immer", nacht_min_temp=19,
             dauer_ab_aussen=16, co2="sensor.co2")
    w = dict(sensor__t_out=12, sensor__rh_out=60, sensor__rh_in=50, sensor__co2=900, sensor__t_in=21.5)
    z.step(3, binary_sensor__win="off", **w)
    s, a = z.step(25, binary_sensor__win="on", **w)
    assert s == "schliessen"


def test_dauerlueften_nicht_sofort_zu_kalt_nach_co2_meldung():
    z = zone(start=dt.datetime(2026, 6, 1, 10, 0), dauerlueften="immer", nacht_min_temp=19, co2="sensor.co2")
    w = dict(sensor__t_out=17, sensor__rh_out=60, sensor__rh_in=50, sensor__t_in=18.8)
    s, a = z.step(3, binary_sensor__win="off", sensor__co2=1250, **w)
    assert s == "lueften"
    s, a = z.step(5, binary_sensor__win="on", sensor__co2=1220, **w)
    assert s == "offen"
    s, a = z.step(4, binary_sensor__win="on", sensor__co2=900, **w)
    assert s == "schliessen" and a["grund"].startswith("Raum zu kalt")


def test_nachtlueftung_schlafzimmer():
    z = zone(start=dt.datetime(2026, 1, 1, 22, 25), dauerlueften="nachts", co2="sensor.co2",
             nacht_beginn="21:00:00", nacht_ende="07:00:00")
    w = dict(sensor__t_out=3, sensor__rh_out=85, sensor__co2=700, sensor__rh_in=52, sensor__t_in=19)
    z.step(3, binary_sensor__win="off", **w)
    z.step(1, binary_sensor__win="on", **w)
    s, a = z.jump(4 * 60, binary_sensor__win="on", **w)
    assert s == "offen"
    s, a = z.jump(5 * 60, binary_sensor__win="on", **w)   # nach 07:00
    assert s == "schliessen" and a["grund"] == "Nachtlüftung beendet"


def _eg(start, **extra):
    z = zone(start=start, dauerlueften="immer", dauer_fenster=["binary_sensor.kueche"],
             dauer_fenster_warm=["binary_sensor.terr"], dauer_ab_aussen=18, dauer_max_min=60,
             nacht_min_temp=19, **extra)
    z.w.set("binary_sensor.win", "off", {"entity_id": ["binary_sensor.kueche", "binary_sensor.terr"]})
    return z


def test_kueche_beim_kochen_max_60_min():
    z = _eg(dt.datetime(2026, 1, 1, 18, 0))
    w = dict(sensor__t_out=8, sensor__rh_out=80, sensor__rh_in=55, sensor__t_in=21)
    z.step(3, binary_sensor__win="off", binary_sensor__kueche="off", binary_sensor__terr="off", **w)
    s, a = z.step(40, binary_sensor__win="on", binary_sensor__kueche="on", binary_sensor__terr="off", **w)
    assert s == "offen"
    s, a = z.step(25, binary_sensor__win="on", binary_sensor__kueche="on", binary_sensor__terr="off", **w)
    assert s == "schliessen" and "Min. offen" in a["grund"]


def test_terrassentuer_sommer_bleibt_offen():
    z = _eg(dt.datetime(2026, 7, 1, 15, 0))
    w = dict(sensor__t_out=30, sensor__rh_out=35, sensor__rh_in=50, sensor__t_in=25)
    z.step(3, binary_sensor__win="off", binary_sensor__kueche="off", binary_sensor__terr="off", **w)
    s, a = z.step(1, binary_sensor__win="on", binary_sensor__kueche="off", binary_sensor__terr="on", **w)
    s, a = z.jump(120, binary_sensor__win="on", binary_sensor__kueche="off", binary_sensor__terr="on", **w)
    assert s == "offen"


def test_kuechenfenster_heiss_aussen_waermer():
    z = _eg(dt.datetime(2026, 7, 1, 15, 0))
    w = dict(sensor__t_out=30, sensor__rh_out=35, sensor__rh_in=50, sensor__t_in=25)
    z.step(3, binary_sensor__win="off", binary_sensor__kueche="off", binary_sensor__terr="off", **w)
    s, a = z.step(5, binary_sensor__win="on", binary_sensor__kueche="on", binary_sensor__terr="off", **w)
    assert s == "schliessen" and "außen wärmer" in a["grund"]


def test_wintergarten_kuehlen_nur_wenn_zone_warm():
    z = zone(start=dt.datetime(2026, 1, 1, 13, 0), temp_kuehlen="sensor.wg")
    s, a = z.step(3, binary_sensor__win="off", sensor__t_out=5, sensor__rh_out=70, sensor__rh_in=45,
                  sensor__t_in=21, sensor__wg=27)
    assert s == "ok"
    s, a = z.step(1, binary_sensor__win="off", sensor__t_out=20, sensor__rh_out=50, sensor__rh_in=50,
                  sensor__t_in=23.5, sensor__wg=30)
    assert s == "lueften" and a["grund"].startswith("Kühlen")


def test_sperre_film_und_danach_lueften():
    z = zone(sperre=["media_player.atv"], sperre_zustaende=["playing", "paused"], grundlueftung_h=24)
    w = dict(sensor__t_out=10, sensor__rh_out=70, sensor__rh_in=50, sensor__t_in=21, binary_sensor__win="off")
    z.step(2, media_player__atv="idle", **w)
    z.step(25, media_player__atv="playing", **w)
    z.step(5, media_player__atv="idle", **w)           # Pause zwischen zwei Folgen
    s, a = z.step(25, media_player__atv="playing", **w)
    assert s == "ok" and a["grundlueftung_faellig"] is False
    s, a = z.step(2, media_player__atv="idle", **w)
    assert s == "ok"                                    # frühestens 5 Min. nach Ende
    s, a = z.step(5, media_player__atv="idle", **w)
    assert s == "lueften" and "Nach Film lüften" in a["grund"]


def test_aktivitaet_3d_druck():
    z = zone(co2="sensor.co2", aktivitaet=["sensor.drucker"], aktiv_zustaende=["running"],
             aktivitaet_name="3D-Druck")
    w = dict(sensor__t_in=21, sensor__rh_in=50, sensor__co2=600, **AUSSEN_WINTER)
    s, a = z.step(2, binary_sensor__win="off", sensor__drucker="idle", **w)
    assert s == "ok"
    s, a = z.step(1, binary_sensor__win="off", sensor__drucker="running", **w)
    assert s == "lueften" and "3D-Druck läuft" in a["grund"]


def test_feuchte_geraet_lebt_kein_ausfall():
    z = zone()
    z.w.devices["dev1"] = ["sensor.t_in", "sensor.rh_in"]
    z.step(1, binary_sensor__win="off", sensor__t_in=21, sensor__rh_in=50, **AUSSEN_WINTER)
    for i in range(24):    # 4 h: nur die Temperatur meldet
        s, a = z.jump(10, sensor__t_in=21 + (i % 2) * 0.1, **AUSSEN_WINTER)
    assert s != "keine_daten" and a["veraltet"] == []


def test_batterien_werden_automatisch_erkannt():
    z = zone()
    z.w.devices["thermo"] = ["sensor.t_in", "sensor.rh_in", "sensor.thermo_batterie", "sensor.thermo_rssi"]
    z.w.set("sensor.thermo_batterie", 12, {"device_class": "battery"})
    z.w.set("sensor.thermo_rssi", -80, {"device_class": "signal_strength"})
    s, a = z.step(1, binary_sensor__win="off", sensor__t_in=21, sensor__rh_in=50, **AUSSEN_WINTER)
    assert a["batterien"] == ["sensor.thermo_batterie"]


def test_dringend_mit_hysterese():
    z = zone(co2="sensor.co2")
    w = dict(sensor__t_in=21, sensor__rh_in=50, **AUSSEN_WINTER)
    z.step(2, binary_sensor__win="off", sensor__co2=900, **w)
    folge = [z.step(1, binary_sensor__win="off", sensor__co2=c, **w)[0] for c in (1510, 1490, 1510, 1450, 1390)]
    assert folge == ["dringend", "dringend", "dringend", "dringend", "lueften"]


def test_nach_film_nicht_bei_heisser_feuchter_aussenluft():
    z = zone(start=dt.datetime(2026, 7, 1, 20, 0), sperre=["media_player.atv"], sperre_zustaende=["playing"])
    w = dict(sensor__t_out=31, sensor__rh_out=70, sensor__rh_in=50, sensor__t_in=24, binary_sensor__win="off")
    z.step(2, media_player__atv="idle", **w)
    z.step(60, media_player__atv="playing", **w)
    s, a = z.step(10, media_player__atv="idle", **w)
    assert "Nach Film" not in a["grund"]


def test_hysterese_nur_fuer_den_aktiven_grund():
    """Nach einer Feuchtespitze darf der Raum nicht wegen 65–70 % Wandfeuchte auf „lüften“ kleben."""
    z = zone(start=dt.datetime(2026, 1, 1, 7, 0))
    w = dict(sensor__t_out=5, sensor__rh_out=80, sensor__t_in=21, binary_sensor__win="off")
    z.step(1, sensor__rh_in=50, **w)
    z.w.states["sensor.luftung_test"]["attrs"]["zuletzt_gelueftet"] = z.w.now - 5 * 3600
    s, a = z.step(15, sensor__rh_in=50, **w)
    assert s == "ok" and 65 <= a["wand_rf"] < 68
    s, a = z.step(1, sensor__rh_in=72, **w)                  # Duschen
    assert s == "dringend"
    s, a = z.step(15, sensor__rh_in=50, **w)                 # wieder Ausgangswert, Fenster blieb zu
    assert s == "ok", a["grund"]


def test_feuchte_pause_nach_dem_lueften():
    z = zone(start=dt.datetime(2026, 1, 1, 9, 0), feuchte_pause=120)
    w = dict(sensor__t_out=5, sensor__rh_out=80, sensor__t_in=21)
    z.step(1, binary_sensor__win="off", sensor__rh_in=64, **w)
    z.w.states["sensor.luftung_test"]["attrs"]["zuletzt_gelueftet"] = z.w.now - 5 * 3600
    s, a = z.step(3, binary_sensor__win="off", sensor__rh_in=64, **w)
    assert s == "lueften" and "Feuchte, Wand" in a["grund"]
    z.step(6, binary_sensor__win="on", sensor__rh_in=55, **w)
    s, a = z.step(40, binary_sensor__win="off", sensor__rh_in=64, **w)   # Feuchte wieder da
    assert s == "ok"
    s, a = z.jump(90, binary_sensor__win="off", sensor__rh_in=64, **w)   # nach 2 h wieder erlaubt
    assert s == "lueften"


def test_fenstergruppe_zeit_der_gruppe():
    z = zone(start=dt.datetime(2026, 1, 1, 12, 0))
    w = dict(sensor__t_out=8, sensor__rh_out=80, sensor__rh_in=50, sensor__t_in=21)
    z.w.set("binary_sensor.kueche", "off")
    z.w.set("binary_sensor.terr", "off")
    z.w.set("binary_sensor.win", "off", {"entity_id": ["binary_sensor.kueche", "binary_sensor.terr"]})
    z.step(60, binary_sensor__kueche="off", binary_sensor__terr="off", **w)   # Küche seit 60 Min. unverändert
    s, a = z.step(1, binary_sensor__win="on", binary_sensor__terr="on", **w)
    assert s == "offen" and a["offen_min"] < 2


def test_hohes_co2_nicht_zu_frueh_schliessen():
    z = zone(start=dt.datetime(2026, 1, 1, 15, 0), co2="sensor.co2", messintervall=5)
    w = dict(sensor__t_out=9.5, sensor__rh_out=70, sensor__rh_in=50, sensor__t_in=21)
    z.step(3, binary_sensor__win="off", sensor__co2=3000, **w)
    co2 = 3000
    for m in range(12):
        co2 -= 60
        s, a = z.step(1, binary_sensor__win="on", sensor__co2=co2, **w)
    assert co2 > 1200 and s == "offen"                     # 12 Min. offen, CO₂ noch hoch
    s, a = z.step(20, binary_sensor__win="on", sensor__co2=co2, **w)
    assert s == "schliessen"                               # spätestens nach 3× Maximaldauer


def test_frost_keine_endlosschleife_bei_trockener_luft():
    z = zone(start=dt.datetime(2026, 1, 1, 10, 0))
    w = dict(sensor__t_out=-5, sensor__rh_out=80, sensor__t_in=21, binary_sensor__win="off")
    z.step(1, sensor__rh_in=36, **w)
    z.w.states["sensor.luftung_test"]["attrs"]["schimmel_stunden"] = 30
    s, a = z.step(1, sensor__rh_in=36, **w)
    assert s == "ok", a["grund"]

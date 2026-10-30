# Lüftungsempfehlung pro Raum (v2)

Zwei Blueprints, die zusammenarbeiten:

| Datei | Typ | Zweck |
|---|---|---|
| [`blueprints/template/lueftung/lueftungsstatus_raum.yaml`](../blueprints/template/lueftung/lueftungsstatus_raum.yaml) | Template | Ein Status-Sensor pro Lüftungszone: `ok` / `lueften` / `dringend` / `offen` / `schliessen` / `keine_daten` |
| [`blueprints/automation/lueftung/lueftung_benachrichtigung.yaml`](../blueprints/automation/lueftung/lueftung_benachrichtigung.yaml) | Automation | Zentrale Benachrichtigung für alle Zonen |
| [`examples/packages/lueftung.yaml`](../examples/packages/lueftung.yaml) | Beispiel | Package mit Zonen, Mittelwerten, Übersicht, Vorhersage-Sensor |

Eine **Zone** ist ein Bereich mit gemeinsamer Luft (keine geschlossenen Türen dazwischen).
Offene Grundrisse werden über Gruppen-Mittelwerte zu einer Zone zusammengefasst.

## Was bewertet wird

- **Feuchte:** absolute Feuchte innen/außen (Magnus), Oberflächen-rF an der kältesten Wandstelle
  (gemessen oder über den Temperaturfaktor fRsi nach DIN 4108-2 geschätzt)
- **Schimmelrisiko über Zeit:** gleitende Feuchtestunden (Wand-rF ≥ 80 % voll, 75–80 % halb, Abklingzeit ca. 3 Tage)
- **CO₂** (optional): Richtwerte nach UBA; Sommer-Block bei feuchter Außenluft
- **Grundlüftung (optional):** Zonen ohne CO₂-Wert, die länger als `grundlueftung_h` (Standard 24 h) nicht gelüftet
  wurden, bleiben „ok“ mit dem Hinweis „Grundlüftung fällig“ (Attribut `grundlueftung_faellig`); die Benachrichtigung
  erwähnt sie nur, wenn ohnehin ein anderer Raum gelüftet werden muss. Nicht bei feuchterer oder wärmerer Außenluft,
  optional erst ab einer Uhrzeit (z. B. Bad nach der Duschzeit)
- **Dauerlüften** (optional, `dauerlueften: nachts` oder `immer`): z. B. Schlafzimmer nachts oder Büro tagsüber –
  das Fenster darf offen bleiben; Meldung „schließen“ nur, wenn etwas dagegen spricht: Raum zu kalt
  (`nacht_min_temp`, Standard 16 °C), Außenluft deutlich feuchter oder wärmer, Raumluft zu trocken, optional nach
  `dauer_max_min` Minuten (nur in der Heizsaison). Wird jede Minute neu bewertet – wer statt zu schließen
  kippt, bekommt keine weiteren Erinnerungen, sobald sich der Raum erholt. Mit `dauer_ab_aussen` (z. B. 16 °C)
  gilt Dauerlüften erst ab dieser Außentemperatur, darunter die normalen Stoßlüft-Regeln.
  `dauer_fenster_warm`: Türen, die nur bei warmem Wetter offen bleiben dürfen (z. B. Terrassentür, solange man
  draußen sitzt) – für sie ist „außen wärmer“ kein Grund zum Schließen. Mit `dauer_fenster` gilt das nur für bestimmte Fenster (z. B. Küchenfenster beim Kochen),
  sind weitere Öffnungen der Zone offen (Gruppe), gelten die normalen Regeln. Bei `nachts` zum Ende des Nachtfensters in der Heizsaison:
  „Nachtlüftung beendet“ (`nachtlueften: true` aus älteren Versionen entspricht `nachts`)
- **Lüftungssperre** (optional, `sperre`): z. B. Beamer/AV-Receiver im Heimkino – während eines Films keine
  Lüftempfehlung („Lüften pausiert (Film)“), danach (ab `sperre_min` Minuten Laufzeit) „Nach Film lüften“
- **Kühl-Temperatur** (optional, `temp_kuehlen`): eigener Sensor, der Kühlen auslöst, z. B. der wärmste
  Raumteil (Wintergarten) in einer offenen Zone – nur wenn auch die Zone selbst warm ist (in der Heizsaison ist
  Sonnenwärme willkommen)
- **Aktivitäten** (optional): z. B. 3D-Druck, Trockner – Lüftempfehlung während und kurz nach der Aktivität
- **Feuchtespitzen** (Duschen, Kochen), **Hitzetage** (Vorkühlen anhand der Tagesvorhersage)
- **Beim Lüften:** Wirksamkeit über CO₂-/Feuchte-Abfallrate (Plateau), Max-Dauer nach Außentemperatur,
  Temperaturabfall, „Raumluft zu trocken“, „Außenluft feuchter“, „außen wärmer“.
  Ab 18 °C außen keine Maximaldauer und keine Plateau-Regel (kein Heizverlust – Dauerlüften erlaubt)
- **Robustheit:** Hysterese, Pause nach dem Lüften, Plausibilitätsgrenzen, veraltete Werte,
  Schutz vor eingefrorenen Sensoren, Modus ohne Fensterkontakt (Öffnen wird aus Messwerten geschätzt)

## Benachrichtigungen

Grundsatz: wenige, gesammelte Nachrichten – aber Erinnerungen, solange wirklich etwas zu tun ist.

| Nachricht | Wann | An wen | Erinnerung |
|---|---|---|---|
| 🪟 **Jetzt lüften** (alle Räume in einer Nachricht) | Raum 10 Min. stabil „lüften“, „dringend“ sofort; nachgeholt nach Ruhezeit, Heimkommen und Regenende | Anwesende | 30, 60, 120 … Min. („dringend“: 15, 30, 60 …) |
| ✅ **Gelüftet: Büro, WC …** | einige Min. nach dem letzten geöffneten Fenster der Runde; vergessene Pflicht-Räume werden genannt | Anwesende (still) | – |
| 🪟 **Fenster schließen (n)** (alle Räume) | 90 s gesammelt nach dem ersten Raum; nachgeholt nach Ruhezeit, Heimkommen, Neustart | Anwesende | 10, 20, 40, 80 … Min. |
| ✅ **… geschlossen** | geschlossene Räume verschwinden still aus der Liste | Anwesende (still) | – |
| ⚠️ **Niemand zu Hause – Fenster offen** | beim Verlassen | alle | – |
| 🌧/⛈ **Regen/Unwetter – Fenster offen** | wenn es zu regnen beginnt bzw. Unwetter/Sturm aufkommt (nicht bei jedem Wechsel rainy ↔ pouring) | Anwesende, sonst alle | – |
| ⚠️ **Zone ohne Werte** | 30 Min. keine Innenwerte | alle | – |
| 🔧 **Sensorbericht** | täglich (18 Uhr), nur wenn etwas auffällt | alle (still) | – |

- **Niemand zu Hause:** keine Lüft- oder Schließ-Erinnerungen; die Abwesenheitswarnung nennt offene Fenster
  einmalig („sollte geschlossen werden“). Nach dem Heimkommen werden offene Punkte nachgeholt.
- **Ruhezeit** (22–7 Uhr): keine Aufforderungen, außer „Schließen“-Hinweise sind ausdrücklich auch nachts erlaubt.
- **Grundlüftung** meldet sich nie allein: Sie wird nur erwähnt, wenn ohnehin ein anderer Raum gelüftet werden
  muss („Bei der Gelegenheit auch: …“ – alles auf einmal); bei Regen/Unwetter entfällt sie.
  Optional: sofort oder als tägliche Sammelmeldung.
- Erinnerungen werden zustandslos berechnet (alle 5 Min. geprüft) und überstehen Neustarts.
- Erledigte Nachrichten werden auf allen Geräten (und optional in der Web-UI) entfernt bzw. still ersetzt.

## Installation

1. **Template-Blueprint** nach `config/blueprints/template/lueftung/` kopieren
   (Template-Blueprints lassen sich nicht über die UI importieren).
2. `examples/packages/lueftung.yaml` nach `config/packages/` kopieren, Entity-IDs anpassen und
   Packages in `configuration.yaml` aktivieren:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
3. Konfiguration prüfen, Home Assistant neu starten.
4. **Automation-Blueprint** importieren (Einstellungen → Automationen & Szenen → Blueprints → Importieren):
   ```
   https://github.com/cernst1980/homeassistant-blueprints/blob/main/blueprints/automation/lueftung/lueftung_benachrichtigung.yaml
   ```
5. Automation aus dem Blueprint anlegen.

## Sensorausfälle und Batterien

- Jede Bewertung läuft, solange ihre Werte da sind (CO₂ allein, Feuchte/Schimmel mit Innen- und Außenwerten,
  Grundlüftung mit dem Fenster). Fehlende Teile stehen im Attribut `einschraenkungen`.
- **Frische pro Gerät:** BLE-/Zigbee-Sensoren melden oft nur bei Änderung. Ein Wert gilt als frisch, solange
  irgendeine Entität desselben Geräts meldet; erst nach `max_alter` (Standard 180 Min.) Stille gilt er als veraltet.
- Gruppen-Mittelwerte rechnen mit den verbleibenden Sensoren weiter.
- Fensterkontakt nicht verfügbar → Öffnen wird aus den Messwerten geschätzt.
- Außenwerte mit Rückfall auf den Wetterdienst – auch, wenn der Außensensor zwar einen Wert hat, aber
  seit 60 Min. nicht mehr meldet (siehe Beispiel-Package).
- Status `keine_daten`, wenn eine Zone keinen Innenwert mehr hat → Meldung nach 30 Min.; offene Lüft-/Schließ-
  Nachrichten der Zone werden entfernt.
- **Batterien** der verwendeten Geräte werden automatisch erkannt (Attribut `batterien`, Sensoren mit
  `device_class: battery` bzw. Low-Battery-Binärsensoren). Schwache (< 15 %) oder nicht verfügbare Batterien
  stehen im täglichen Sensorbericht.
- Der Sensorbericht meldet außerdem ausgefallene Einzel- und Gruppensensoren, eingeschränkte Bewertungen und
  Status-Sensoren, die nicht mehr rechnen (Template-Fehler).
- Fällt ein Handy weg (umbenannt, App gelöscht), laufen die Benachrichtigungen an die anderen weiter.

## Hinweise

- **Sensoren, die nur bei Wertänderung melden** (BLE wie ThermoPro/SwitchBot, viele Zigbee-Geräte):
  „keine neue Meldung“ bedeutet „unverändert“. Ein Wert gilt als frisch, solange irgendeine Entität desselben
  Geräts (bzw. der Gruppenmitglieder) meldet – konstante Feuchte bei weiter meldender Temperatur ist kein Ausfall.
  Erst wenn das ganze Gerät `max_alter` (Standard 180 Min.) still ist, gilt der Wert als veraltet.
- **Sensoren mit festem Messintervall** (z. B. SwitchBot Meter Pro CO2: 5 Min.): `messintervall` setzen,
  damit die Abfallraten immer zwei echte Messungen vergleichen.
- Die Zonen-Sensoren schreiben jede Minute neue Attribute → per `recorder: exclude` ausschließen
  (siehe Beispiel-Package) und für die Historie den Übersichtssensor nutzen.
- Raumnamen (`raum`) müssen eindeutig sein.
- `dauer_fenster` (z. B. Küchenfenster beim Kochen) erkennt das Kochen selbst nicht: Jede Öffnung dieses
  Fensters darf bis `dauer_max_min` offen bleiben.

Getestet mit Home Assistant 2026.9.

## Tests

`tests/lueftung` spielt typische Abläufe mit einem kleinen HA-Nachbau durch (`ha_sim.py`):
CO₂-Lüften und Plateau, Maximaldauer, Grundlüftung, Dauerlüften, Küche/Terrasse, Wintergarten,
Sperre, 3D-Druck, Hysterese, Sensorausfälle, Batterien sowie Raumlisten, Erinnerungsabstände,
Wetterwarnungen und Bestätigungen der Benachrichtigung.
Sie laufen bei jedem Push automatisch (`python3 -m pytest tests -q`).

[← Zurück zur Übersicht](../README.md)

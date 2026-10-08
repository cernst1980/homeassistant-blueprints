# Lüftungsempfehlung pro Raum (v2)

Zwei Blueprints, die zusammenarbeiten:

| Datei | Typ | Zweck |
|---|---|---|
| [`blueprints/template/lueftung/lueftungsstatus_raum.yaml`](../blueprints/template/lueftung/lueftungsstatus_raum.yaml) | Template | Ein Status-Sensor pro Lüftungszone: `ok` / `lueften` / `dringend` / `offen` / `schliessen` |
| [`blueprints/automation/lueftung/lueftung_benachrichtigung.yaml`](../blueprints/automation/lueftung/lueftung_benachrichtigung.yaml) | Automation | Zentrale Benachrichtigung für alle Zonen |
| [`examples/packages/lueftung.yaml`](../examples/packages/lueftung.yaml) | Beispiel | Package mit Zonen, Mittelwerten, Übersicht, Vorhersage-Sensor |

Eine **Zone** ist ein Bereich mit gemeinsamer Luft (keine geschlossenen Türen dazwischen).
Offene Grundrisse werden über Gruppen-Mittelwerte zu einer Zone zusammengefasst.

## Was bewertet wird

- **Feuchte:** absolute Feuchte innen/außen (Magnus), Oberflächen-rF an der kältesten Wandstelle
  (gemessen oder über den Temperaturfaktor fRsi nach DIN 4108-2 geschätzt)
- **Schimmelrisiko über Zeit:** gleitende Feuchtestunden (Wand-rF ≥ 80 % voll, 75–80 % halb, Abklingzeit ca. 3 Tage)
- **CO₂** (optional): Richtwerte nach UBA; Sommer-Block bei feuchter Außenluft
- **Grundlüftung:** Zonen ohne CO₂-Wert bekommen spätestens alle 8 h (einstellbar) eine Lüftempfehlung –
  nicht bei feuchterer oder wärmerer Außenluft, optional erst ab einer Uhrzeit (z. B. Bad nach der Duschzeit)
- **Dauerlüften** (optional, `dauerlueften: nachts` oder `immer`): z. B. Schlafzimmer nachts oder Büro tagsüber –
  das Fenster darf offen bleiben; Meldung „schließen oder nur kippen“ nur, wenn etwas dagegen spricht: Raum zu kalt
  (`nacht_min_temp`, Standard 16 °C), Außenluft deutlich feuchter oder wärmer, Raumluft zu trocken, optional nach
  `dauer_max_min` Minuten. Mit `dauer_fenster` gilt das nur für bestimmte Fenster (z. B. Küchenfenster beim Kochen),
  andere Öffnungen der Zone werden normal bewertet. Bei `nachts` zum Ende des Nachtfensters in der Heizsaison:
  „Nachtlüftung beendet“ (`nachtlueften: true` aus älteren Versionen entspricht `nachts`)
- **Lüftungssperre** (optional, `sperre`): z. B. Beamer/AV-Receiver im Heimkino – während eines Films keine
  Lüftempfehlung („Lüften pausiert (Film)“), danach (ab `sperre_min` Minuten Laufzeit) „Nach Film lüften“
- **Kühl-Temperatur** (optional, `temp_kuehlen`): eigener Sensor für Kühlen/„außen wärmer“, z. B. der wärmste
  Raumteil (Wintergarten) in einer offenen Zone
- **Aktivitäten** (optional): z. B. 3D-Druck, Trockner – Lüftempfehlung während und kurz nach der Aktivität
- **Feuchtespitzen** (Duschen, Kochen), **Hitzetage** (Vorkühlen anhand der Tagesvorhersage)
- **Beim Lüften:** Wirksamkeit über CO₂-/Feuchte-Abfallrate (Plateau), Max-Dauer nach Außentemperatur,
  Temperaturabfall, „Raumluft zu trocken“, „Außenluft feuchter“, „außen wärmer“.
  Ab 18 °C außen keine Maximaldauer und keine Plateau-Regel (kein Heizverlust – Dauerlüften erlaubt)
- **Robustheit:** Hysterese, Pause nach dem Lüften, Plausibilitätsgrenzen, veraltete Werte,
  Schutz vor eingefrorenen Sensoren, Modus ohne Fensterkontakt (Öffnen wird aus Messwerten geschätzt)

## Benachrichtigungen

- „Jetzt lüften“ gebündelt, nur an Geräte zu Hause, Ruhezeit, Querlüften-Tipp, Regen-/Unwetter-Hinweis
- „Fenster schließen“ pro Zone mit Erinnerung; in der Ruhezeit erst morgens (z. B. gekipptes Schlafzimmerfenster)
- Offene Empfehlungen werden nach der Ruhezeit und nach dem Heimkommen nachgeholt
- Erinnerung bei Nichtbeachtung („lüften“ alle 30 Min., „dringend“ alle 15 Min.)
- Warnung bei offenen Fenstern beim Verlassen des Hauses und bei Regen/Unwetter
  (Zonen mit `regengeschuetzt: true`, z. B. unter Vordach, nur bei Unwetter)
- Reine Grundlüftung wird bei Regen/Unwetter zurückgestellt und nach dem Regen nachgeholt
- Erledigte Nachrichten werden auf allen Geräten (und optional in der Web-UI) entfernt

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

## Sensorausfälle

- Jede Bewertung läuft, solange ihre Werte da sind (CO₂ allein, Feuchte/Schimmel mit Innen- und Außenwerten,
  Grundlüftung mit dem Fenster). Fehlende Teile stehen im Attribut `einschraenkungen`.
- Gruppen-Mittelwerte rechnen mit den verbleibenden Sensoren weiter.
- Fensterkontakt nicht verfügbar → Öffnen wird aus den Messwerten geschätzt.
- Außenwerte optional mit Rückfall auf den Wetterdienst (siehe Beispiel-Package).
- Status `keine_daten`, wenn eine Zone keinen Innenwert mehr hat → sofortige Meldung nach 30 Min.
- Täglicher Sensorbericht: ausgefallene Einzel- und Gruppensensoren, Einschränkungen, schwache Batterien.

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

Getestet mit Home Assistant 2026.9.

[← Zurück zur Übersicht](../README.md)

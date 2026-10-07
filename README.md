# Home Assistant Blueprints

## Lüftungsempfehlung pro Raum (v2)

Zwei Blueprints, die zusammenarbeiten:

| Datei | Typ | Zweck |
|---|---|---|
| `blueprints/template/lueftung/lueftungsstatus_raum.yaml` | Template | Ein Status-Sensor pro Lüftungszone: `ok` / `lueften` / `dringend` / `offen` / `schliessen` |
| `blueprints/automation/lueftung/lueftung_benachrichtigung.yaml` | Automation | Zentrale Benachrichtigung für alle Zonen |
| `examples/packages/lueftung.yaml` | Beispiel | Package mit Zonen, Mittelwerten, Übersicht, Vorhersage-Sensor |

Eine **Zone** ist ein Bereich mit gemeinsamer Luft (keine geschlossenen Türen dazwischen).
Offene Grundrisse werden über Gruppen-Mittelwerte zu einer Zone zusammengefasst.

### Was bewertet wird

- **Feuchte:** absolute Feuchte innen/außen (Magnus), Oberflächen-rF an der kältesten Wandstelle
  (gemessen oder über den Temperaturfaktor fRsi nach DIN 4108-2 geschätzt)
- **Schimmelrisiko über Zeit:** gleitende Feuchtestunden (Wand-rF ≥ 80 % voll, 75–80 % halb, Abklingzeit ca. 3 Tage)
- **CO₂** (optional): Richtwerte nach UBA; Sommer-Block bei feuchter Außenluft
- **Grundlüftung:** Zonen ohne CO₂-Wert bekommen spätestens alle 8 h (einstellbar) eine Lüftempfehlung
- **Aktivitäten** (optional): z. B. 3D-Druck, Trockner – Lüftempfehlung während und kurz nach der Aktivität
- **Feuchtespitzen** (Duschen, Kochen), **Hitzetage** (Vorkühlen anhand der Tagesvorhersage)
- **Beim Lüften:** Wirksamkeit über CO₂-/Feuchte-Abfallrate (Plateau), Max-Dauer nach Außentemperatur,
  Temperaturabfall, „Raumluft zu trocken“, „Außenluft feuchter“, „außen wärmer“.
  Ab 18 °C außen keine Maximaldauer und keine Plateau-Regel (kein Heizverlust – Dauerlüften erlaubt)
- **Robustheit:** Hysterese, Pause nach dem Lüften, Plausibilitätsgrenzen, veraltete Werte,
  Schutz vor eingefrorenen Sensoren, Modus ohne Fensterkontakt (Öffnen wird aus Messwerten geschätzt)

### Benachrichtigungen

- „Jetzt lüften“ gebündelt, nur an Geräte zu Hause, Ruhezeit, Querlüften-Tipp, Regen-/Unwetter-Hinweis
- „Fenster schließen“ pro Zone mit Erinnerung; in der Ruhezeit erst morgens (z. B. gekipptes Schlafzimmerfenster)
- Offene Empfehlungen werden nach der Ruhezeit und nach dem Heimkommen nachgeholt
- Erinnerung bei Nichtbeachtung („lüften“ alle 30 Min., „dringend“ alle 15 Min.)
- Warnung bei offenen Fenstern beim Verlassen des Hauses und bei Regen/Unwetter
- Erledigte Nachrichten werden auf allen Geräten (und optional in der Web-UI) entfernt

### Installation

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

### Sensorausfälle

- Jede Bewertung läuft, solange ihre Werte da sind (CO₂ allein, Feuchte/Schimmel mit Innen- und Außenwerten,
  Grundlüftung mit dem Fenster). Fehlende Teile stehen im Attribut `einschraenkungen`.
- Gruppen-Mittelwerte rechnen mit den verbleibenden Sensoren weiter.
- Fensterkontakt nicht verfügbar → Öffnen wird aus den Messwerten geschätzt.
- Außenwerte optional mit Rückfall auf den Wetterdienst (siehe Beispiel-Package).
- Status `keine_daten`, wenn eine Zone keinen Innenwert mehr hat → sofortige Meldung nach 30 Min.
- Täglicher Sensorbericht: ausgefallene Einzel- und Gruppensensoren, Einschränkungen, schwache Batterien.

### Hinweise

- **Sensoren, die nur bei Wertänderung melden** (BLE wie ThermoPro/SwitchBot, viele Zigbee-Geräte):
  „keine neue Meldung“ bedeutet „unverändert“. Deshalb ist `max_alter` standardmäßig 180 Minuten.
- **Sensoren mit festem Messintervall** (z. B. SwitchBot Meter Pro CO2: 5 Min.): `messintervall` setzen,
  damit die Abfallraten immer zwei echte Messungen vergleichen.
- Die Zonen-Sensoren schreiben jede Minute neue Attribute → per `recorder: exclude` ausschließen
  (siehe Beispiel-Package) und für die Historie den Übersichtssensor nutzen.
- Raumnamen (`raum`) müssen eindeutig sein.

Getestet mit Home Assistant 2026.9.

## Tank-Assistent (Spritpreis-Optimierung)

Plant für ein Auto, **wann und wo** sich Tanken am meisten lohnt, ohne mit leerem Tank
liegen zu bleiben. Lernt dafür Preisprofile, Öffnungszeiten und das eigene Fahrprofil.

| Datei | Typ | Zweck |
|---|---|---|
| `appdaemon/apps/tank_assistent/` | AppDaemon-App | Lernen, Planung (Optimierung), Entitäten per MQTT Discovery, Meldungs-Events |
| `blueprints/automation/tank/tank_benachrichtigung.yaml` | Automation | Push-Nachrichten, optional mit KI-Begründung (z. B. Gemini), Buttons |
| `examples/dashboards/tank_assistent.yaml` | Beispiel | Dashboard-Karte |
| `tools/tank_backtest.py` | Werkzeug | Backtest der Strategie auf echten oder synthetischen Daten |
| `tests/tank_assistent/` | Tests | pytest (Kernlogik und App mit AppDaemon-Stub) |

### Was gelernt wird

- **Preisprofil** je Tankstelle nach Wochentag × Stunde, ausgerichtet auf die **12-Uhr-Regel**
  (seit 1.4.2026 dürfen Preise nur um 12 Uhr steigen, sinken jederzeit). Ob es kurz vor 12 Uhr
  oder abends am günstigsten ist, ergibt sich aus den Daten.
- **Preistrend** (gedämpft fortgeschrieben), **Feiertags-** und **Ferienbeginn-Effekt**
  (Feiertage Bayern, Schulferien über [OpenHolidays](https://openholidaysapi.org)).
- **Öffnungszeiten** je Tankstelle aus dem Tankerkönig-Status (30-Minuten-Raster).
- **Fahrprofil**: km je Tagestyp (Mo … Sa, Sonntag/Feiertag) aus dem Kilometerstand,
  Verbrauch (l/100 km) aus Tankstand und Kilometerstand.
- **Effektivpreis** = Preis − Rabatt (z. B. ADAC bei ESSO/AGIP, zeitabhängig konfigurierbar).

### Wie entschieden wird

Jede Stunde im Verfügbarkeitszeitraum, in der eine Tankstelle offen ist, ist ein möglicher
Tankzeitpunkt – bis der Tank (konservativ gerechnet) die Reserve erreicht. Getankt wird immer voll.
Verglichen werden die Kosten **für dieselbe Strecke**:

```
kosten(zeitpunkt) = liter_die_dann_passen × (erwarteter_preis − langfristiger_preis)
```

Eine Rückwärtsrechnung (optimales Stoppproblem) liefert für jeden Zeitpunkt einen
**Zielpreis**: „tanken, wenn höchstens X“. Daraus ergeben sich die Status
`muss` (Rest reicht nicht bis zur nächsten Gelegenheit), `jetzt`, `heute` und `warten`.
Bis zum nächsten 12-Uhr-Sprung ist der aktuelle Preis eine garantierte Obergrenze –
Bestätigungen vor dem Termin sind deshalb verlässlich.

### Benachrichtigungen

- **7 Uhr**: Tagesplan (nur wenn heute etwas ansteht, sich der Plan der nächsten zwei Tage
  geändert hat oder morgen eine lange Fahrt erwartet wird – „Bürofahrt-Check“)
- **Vorlauf** (Standard 60 Min.) vor dem empfohlenen Zeitpunkt: „wie geplant“ oder „Preis zu hoch, neuer Plan“
- **Spontan**, wenn Tanken jetzt deutlich günstiger ist als Abwarten (max. alle 3 h, nicht in der Ruhezeit)
- **Muss tanken** einmal am Tag (zeitkritisch)
- **Tankvorgang erkannt** mit Ersparnis und **Wochenbilanz** (sonntags)
- Buttons **Erledigt** / **Später erinnern** (2 h)

### Ersparnis – ehrlich gemessen

Vergleich mit dem **Durchschnittspreis** aller Tankstellen über alle Stunden seit dem letzten
Tanken (was ein Durchschnittsfahrer im selben Zeitraum gezahlt hätte), aufgeteilt in
**Zeitpunkt**, **Tankstellenwahl** und **Rabatt**. Die **Ausschöpfung** zeigt den Anteil der im
Nachhinein bestmöglichen Ersparnis. Tankvorgänge werden am Anstieg des Tankstands erkannt
(≥ 15 Prozentpunkte); mit „Erledigt“ sind Zeit und Tankstelle bestätigt, sonst geschätzt.

### Installation

**Voraussetzungen:** Tankerkönig-Integration (Tankstellen ausgewählt), Fahrzeugsensoren für
Tankstand (%) und Kilometerstand (z. B. VW Group Connect), MQTT-Integration (z. B. Mosquitto),
Companion App. Optional: eine KI-Aufgabe (z. B. Google Gemini → „Google AI Task“).

1. **AppDaemon-Add-on** installieren (Einstellungen → Add-ons → Add-on-Store → AppDaemon).
   In der Add-on-Konfiguration unter `python_packages` `tzdata` eintragen und starten.
2. Ordner `appdaemon/apps/tank_assistent/` nach
   `/addon_configs/a0d7b954_appdaemon/apps/tank_assistent/` kopieren
   (z. B. mit Studio Code Server oder Samba; die Tests werden nicht benötigt).
3. `tank_assistent.yaml.example` als `tank_assistent.yaml` speichern und die Entity-IDs
   der Fahrzeugsensoren eintragen. AppDaemon lädt die App automatisch.
4. Im AppDaemon-Log sollte `Tank-Assistent 1.0.0 gestartet, N Tankstellen` erscheinen.
   Unter Geräte & Dienste → MQTT taucht das Gerät **Tank-Assistent** mit seinen Sensoren auf.
5. **Blueprint** importieren und eine Automation daraus anlegen (Handy und KI-Aufgabe wählen):
   ```
   https://github.com/cernst1980/homeassistant-blueprints/blob/main/blueprints/automation/tank/tank_benachrichtigung.yaml
   ```
6. Optional die **Dashboard-Karte** aus `examples/dashboards/tank_assistent.yaml` einfügen.

Die Lernwerte liegen in `apps/tank_assistent/data/tank_assistent.json` (in den
AppDaemon-Backups enthalten). Nach einem Update der Python-Dateien AppDaemon neu starten.

### Lernphase

- Ab dem ersten Tag wird geplant (mit Startwerten). Das Preisprofil wird nach etwa **1–2 Wochen**
  belastbar, das Fahrprofil nach einigen Wochen. Der Sensor **Lernstand** zeigt die Preistage.
- Fahrzeugdaten über das EU-Data-Act-Portal kommen verzögert (oft erst nach einer Fahrt).
  Ohne Tankstand schätzt die App aus dem letzten Wert und den gefahrenen Kilometern.

### Backtest und Tests

```bash
python3 tools/tank_backtest.py --synthetisch 90
python3 tools/tank_backtest.py --zustand pfad/zu/tank_assistent.json --km "mo=15,di=15,mi=15,do=200,fr=15,sa=25,so=10"
python3 -m pytest tests/tank_assistent
```

## Legacy

`legacy/raum_lueftung.yaml` – alte Version (eine Automation pro Raum mit Helfern).

## Lizenz

MIT – siehe [LICENSE](LICENSE).

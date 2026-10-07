# Tank-Assistent (Spritpreis-Optimierung)

Plant für ein Auto, **wann und wo** sich Tanken am meisten lohnt, ohne mit leerem Tank
liegen zu bleiben. Lernt dafür Preisprofile, Öffnungszeiten und das eigene Fahrprofil.

| Datei | Typ | Zweck |
|---|---|---|
| [`appdaemon/apps/tank_assistent/`](../appdaemon/apps/tank_assistent/) | AppDaemon-App | Lernen, Planung (Optimierung), Entitäten per MQTT Discovery, Meldungs-Events |
| [`blueprints/automation/tank/tank_benachrichtigung.yaml`](../blueprints/automation/tank/tank_benachrichtigung.yaml) | Automation | Push-Nachrichten, optional mit KI-Begründung (z. B. Gemini), Buttons |
| [`examples/dashboards/tank_assistent.yaml`](../examples/dashboards/tank_assistent.yaml) | Beispiel | Dashboard-Karte |
| [`tools/tank_backtest.py`](../tools/tank_backtest.py) | Werkzeug | Backtest der Strategie auf echten oder synthetischen Daten |
| [`tests/tank_assistent/`](../tests/tank_assistent/) | Tests | pytest (Kernlogik und App mit AppDaemon-Stub) |

## Was gelernt wird

- **Preisprofil** je Tankstelle nach Wochentag × Stunde, ausgerichtet auf die **12-Uhr-Regel**
  (seit 1.4.2026 dürfen Preise nur um 12 Uhr steigen, sinken jederzeit). Ob es kurz vor 12 Uhr
  oder abends am günstigsten ist, ergibt sich aus den Daten.
- **Preistrend** (gedämpft fortgeschrieben), **Feiertags-** und **Ferienbeginn-Effekt**
  (Feiertage Bayern, Schulferien über [OpenHolidays](https://openholidaysapi.org)).
- **Öffnungszeiten** je Tankstelle aus dem Tankerkönig-Status (30-Minuten-Raster).
- **Fahrprofil**: km je Tagestyp (Mo … Sa, Sonntag/Feiertag) aus dem Kilometerstand,
  Verbrauch (l/100 km) aus Tankstand und Kilometerstand.
- **Effektivpreis** = Preis − Rabatt (z. B. ADAC bei ESSO/AGIP, zeitabhängig konfigurierbar).

## Wie entschieden wird

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

## Benachrichtigungen

- **7 Uhr**: Tagesplan (nur wenn heute etwas ansteht, sich der Plan der nächsten zwei Tage
  geändert hat oder morgen eine lange Fahrt erwartet wird – „Bürofahrt-Check“)
- **Vorlauf** (Standard 60 Min.) vor dem empfohlenen Zeitpunkt: „wie geplant“ oder „Preis zu hoch, neuer Plan“
- **Spontan**, wenn Tanken jetzt deutlich günstiger ist als Abwarten (max. alle 3 h, nicht in der Ruhezeit)
- **Muss tanken** einmal am Tag (zeitkritisch)
- **Tankvorgang erkannt** mit Ersparnis und **Wochenbilanz** (sonntags)
- Buttons **Erledigt** / **Später erinnern** (2 h)

## Ersparnis – ehrlich gemessen

Vergleich mit dem **Durchschnittspreis** aller Tankstellen über alle Stunden seit dem letzten
Tanken (was ein Durchschnittsfahrer im selben Zeitraum gezahlt hätte), aufgeteilt in
**Zeitpunkt**, **Tankstellenwahl** und **Rabatt**. Die **Ausschöpfung** zeigt den Anteil der im
Nachhinein bestmöglichen Ersparnis. Tankvorgänge werden am Anstieg des Tankstands erkannt
(≥ 15 Prozentpunkte); mit „Erledigt“ sind Zeit und Tankstelle bestätigt, sonst geschätzt.

## Installation

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

## Lernphase

- Ab dem ersten Tag wird geplant (mit Startwerten). Das Preisprofil wird nach etwa **1–2 Wochen**
  belastbar, das Fahrprofil nach einigen Wochen. Der Sensor **Lernstand** zeigt die Preistage.
- Fahrzeugdaten über das EU-Data-Act-Portal kommen verzögert (oft erst nach einer Fahrt).
  Ohne Tankstand schätzt die App aus dem letzten Wert und den gefahrenen Kilometern.

## Backtest und Tests

```bash
python3 tools/tank_backtest.py --synthetisch 90
python3 tools/tank_backtest.py --zustand pfad/zu/tank_assistent.json --km "mo=15,di=15,mi=15,do=200,fr=15,sa=25,so=10"
python3 -m pytest tests/tank_assistent
python3 tools/check_yaml.py      # YAML und Templates aller Projekte
```

Bei jedem Push laufen Tests und YAML-Prüfung automatisch (GitHub Actions).

[← Zurück zur Übersicht](../README.md)

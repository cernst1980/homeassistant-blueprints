# Home Assistant Blueprints

Blueprints, AppDaemon-Apps und Beispiele für Home Assistant.

[![Tests](https://github.com/cernst1980/homeassistant-blueprints/actions/workflows/tests.yml/badge.svg)](https://github.com/cernst1980/homeassistant-blueprints/actions/workflows/tests.yml)

## Projekte

| Projekt | Beschreibung | Bestandteile | Doku |
|---|---|---|---|
| **Lüftungsempfehlung pro Raum** (v2) | Status pro Lüftungszone (Feuchte, Schimmelrisiko, CO₂, Grundlüftung) und zentrale Benachrichtigungen | Template-Blueprint, Automation-Blueprint, Beispiel-Package | [docs/lueftung.md](docs/lueftung.md) |
| **Tank-Assistent** | Lernt Spritpreise, Öffnungszeiten und Fahrprofil und plant, wann und wo sich Tanken am meisten lohnt | AppDaemon-App, Automation-Blueprint, Dashboard, Backtest | [docs/tank_assistent.md](docs/tank_assistent.md) |

## Aufbau des Repos

```
blueprints/              wie config/blueprints/ in Home Assistant
  automation/<projekt>/  Automation-Blueprints (über die UI importierbar)
  template/<projekt>/    Template-Blueprints (manuell kopieren)
appdaemon/apps/<projekt>/  AppDaemon-Apps (Ordner 1:1 ins AppDaemon-Add-on kopieren)
examples/                Beispiel-Packages und Dashboards
docs/                    Ausführliche Doku je Projekt
tests/<projekt>/         Automatische Tests (pytest)
tools/                   Hilfsskripte (Backtest, YAML-Prüfung)
legacy/                  Ältere Versionen
```

## Legacy

`legacy/raum_lueftung.yaml` – alte Version (eine Automation pro Raum mit Helfern).

## Lizenz

MIT – siehe [LICENSE](LICENSE).

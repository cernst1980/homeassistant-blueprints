# Home Assistant Blueprints

## Lüftungsempfehlung pro Raum (v2)

Zwei Blueprints, die zusammenarbeiten:

| Datei | Typ | Zweck |
|---|---|---|
| `blueprints/template/lueftung/lueftungsstatus_raum.yaml` | Template | Ein Status-Sensor pro Raum: `ok` / `lueften` / `dringend` / `offen` / `schliessen` |
| `blueprints/automation/lueftung/lueftung_benachrichtigung.yaml` | Automation | Zentrale Benachrichtigung für alle Räume |
| `examples/packages/lueftung.yaml` | Beispiel | Vorhersage-Sensor und Raum-Sensoren als Package |

### Was bewertet wird

- **Feuchte:** absolute Feuchte innen/außen (Magnus), Oberflächen-rF an der kältesten Wandstelle (gemessen oder über fRsi nach DIN 4108-2 geschätzt)
- **Schimmelrisiko über Zeit:** gleitende Feuchtestunden (Wand-rF ≥ 80 % voll, 75–80 % halb, Abklingzeit ca. 3 Tage)
- **CO₂** (optional): Richtwerte nach UBA, Sommer-Block bei feuchter Außenluft
- **Feuchtespitzen** (Duschen), **Hitzetage** (Vorkühlen anhand der Tagesvorhersage)
- **Beim Lüften:** Wirksamkeit über CO₂-/Feuchte-Abfallrate (Plateau), Max-Dauer nach Außentemperatur, Temperaturabfall, „zu trocken“
- **Robustheit:** Hysterese, Pause nach dem Lüften, veraltete/unplausible Sensorwerte, Modus ohne Fensterkontakt

### Benachrichtigungen

- „Jetzt lüften“ gebündelt, nur an Geräte zu Hause, Ruhezeit, Querlüften-Tipp
- „Fenster schließen“ pro Raum mit Erinnerung
- Warnung bei offenen Fenstern beim Verlassen und bei Regen/Unwetter
- Erledigte Nachrichten werden auf allen Geräten und in der Web-UI entfernt

### Installation

1. **Template-Blueprint** nach `config/blueprints/template/lueftung/` kopieren
   (Template-Blueprints lassen sich nicht über die UI importieren).
2. **Automation-Blueprint** über *Einstellungen → Automationen → Blueprints → Importieren* mit der GitHub-URL importieren.
3. `examples/packages/lueftung.yaml` nach `config/packages/` kopieren, Entity-IDs anpassen, Packages in `configuration.yaml` aktivieren.
4. Konfiguration prüfen, HA neu starten.
5. Automation aus dem Benachrichtigungs-Blueprint anlegen.

Entwickelt für Home Assistant 2026.9 oder neuer.

## Legacy

`legacy/raum_lueftung.yaml` – alte Version (eine Automation pro Raum mit Helfern). Wird nach der Migration entfernt.

### Import-URL (Automation-Blueprint)

```
https://github.com/cernst1980/homeassistant-blueprints/blob/main/blueprints/automation/lueftung/lueftung_benachrichtigung.yaml
```

## Lizenz

MIT – siehe [LICENSE](LICENSE).

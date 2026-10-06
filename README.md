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
- **Feuchtespitzen** (Duschen, Kochen), **Hitzetage** (Vorkühlen anhand der Tagesvorhersage)
- **Beim Lüften:** Wirksamkeit über CO₂-/Feuchte-Abfallrate (Plateau), Max-Dauer nach Außentemperatur,
  Temperaturabfall, „Raumluft zu trocken“, „Außenluft feuchter“, „außen wärmer“
- **Robustheit:** Hysterese, Pause nach dem Lüften, Plausibilitätsgrenzen, veraltete Werte,
  Schutz vor eingefrorenen Sensoren, Modus ohne Fensterkontakt (Öffnen wird aus Messwerten geschätzt)

### Benachrichtigungen

- „Jetzt lüften“ gebündelt, nur an Geräte zu Hause, Ruhezeit, Querlüften-Tipp, Regen-/Unwetter-Hinweis
- „Fenster schließen“ pro Zone mit Erinnerung
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

### Hinweise

- **Sensoren, die nur bei Wertänderung melden** (BLE wie ThermoPro/SwitchBot, viele Zigbee-Geräte):
  „keine neue Meldung“ bedeutet „unverändert“. Deshalb ist `max_alter` standardmäßig 180 Minuten.
- Die Zonen-Sensoren schreiben jede Minute neue Attribute → per `recorder: exclude` ausschließen
  (siehe Beispiel-Package) und für die Historie den Übersichtssensor nutzen.
- Raumnamen (`raum`) müssen eindeutig sein.

Getestet mit Home Assistant 2026.9.

## Legacy

`legacy/raum_lueftung.yaml` – alte Version (eine Automation pro Raum mit Helfern).

## Lizenz

MIT – siehe [LICENSE](LICENSE).

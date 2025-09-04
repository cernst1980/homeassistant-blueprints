# Raumlüftungsempfehlung (Feuchte + CO₂) — Home Assistant Blueprint

**Kurz:** Blueprint zur Raum- bzw. zonenweisen Lüftungsempfehlung. Berücksichtigt relative/absolute Luftfeuchte, optional CO₂, Fensterstatus, Anwesenheit und konfigurierbare Schwellen. Meldungen überschreiben sich und werden automatisch gelöscht, wenn die empfohlene Aktion durchgeführt wurde.

---

## Features

- Empfiehlt **Lüften**, **Fenster schließen** oder sendet **Warnung (Fenster offen bei Abwesenheit)**.
- Nutzt relative und absolute Luftfeuchtigkeit (g/m³) — `diff = abs_in - abs_out`.
- Optionaler CO₂-Sensor wird berücksichtigt.
- **Summer-Block** verhindert Lüften, wenn Außenluft deutlich feuchter ist.
- Meldungen werden auf ein konfigurierbares Intervall begrenzt (z. B. 24 h).
- Push-Benachrichtigungen (Companion App) verwendet `tag` → alte Meldungen werden per `clear_notification` überschrieben.
- Persistente Notifications in WebUI werden per `persistent_notification.dismiss` entfernt.
- Unterstützt Räume **mit und ohne Fenstersensoren** (Clearing-Logik berücksichtigt fehlende Sensoren).

---

## Installation

1. Datei `raum_lueftung.yaml` in dein `blueprints/automation/` Repository legen.
2. In Home Assistant: **Einstellungen → Automatisierungen & Szenen → Blueprints → Importieren** (oder über Dateiablage).
3. Beim Erstellen einer Automation auf Basis des Blueprints folgende Entities angeben:
   - `indoor_humidity` (sensor, device_class: humidity)
   - `indoor_absolute` (sensor)
   - `outdoor_absolute` (sensor)
   - (optional) `window_sensors` (binary_sensor(s), device_class: window/door)
   - (optional) `presence_persons` (person entities)
   - (optional) `co2_sensor` (sensor, device_class: carbon_dioxide)
   - `notify_targets` (mobile app devices)
   - `helper_status` (input_text) — **muss** angelegt werden
   - `helper_last_notify` (input_datetime) — **muss** angelegt werden

> Hinweis: Blueprints können Helfer nicht automatisch erstellen. Lege `input_text` und `input_datetime` per GUI an (Einstellungen → Hilfsmittel).

---

## Empfohlene Default-Werte (wie im Blueprint gesetzt)

- `threshold_relative` (rF): **60 %**  
- `threshold_difference` (Δabs, innen−außen): **1.5 g/m³** (Lüften ab ≈1.5)  
- `close_diff_threshold` (Δabs zum Schließen): **0.5 g/m³**  
- `close_rh_threshold` (rF zum Schließen): **50 %**  
- `co2_threshold`: **1200 ppm** (für Schlafzimmer/Arbeitszimmer ggf. 900–1000)  
- `min_vent_duration`: **20 Minuten** (gut für Kippfenster; Stoßlüftung kann kürzer sein)  
- `summer_block_threshold`: **2 g/m³** (blockiert Lüften, wenn draußen um ≥2 g/m³ feuchter)  
- `notify_repeat_hours`: **24** (max. eine Meldung pro Tag; anpassbar)

---

## Erläuterungen / Designentscheidungen

- **Δabs (abs_in - abs_out)** ist wichtiger als nur relative LF; absolute Differenz zeigt den realen Trocknungsvorteil durch Außenluft.
- **Lüften** wird empfohlen wenn Δabs groß genug ist **oder** rF hoch ist **oder** CO₂ zu hoch ist.
- **Schließen** erfolgt wenn Δabs klein geworden ist (kein Gewinn mehr) **oder** die relative Luftfeuchte bereits niedrig ist.
- **Summer-Block** schützt vor Feuchteeintrag, wenn draußen deutlich feuchter ist.
- **Clearing**:
  - Bei Räumen **mit** Fenstersensoren: messages werden automatisch gelöscht, wenn Zielzustand erreicht ist (Fenster offen/geschlossen).
  - Bei Räumen **ohne** Fenstersensoren: Lüften/Schließen-Meldungen werden nicht automatisch wegen Fenstermangel gecleart; Warnung (Abwesenheit) wird beim Heimkommen gecleart.

---

## Hinweise & Troubleshooting

- Wenn du viele False-Positives siehst, erhöhe `threshold_difference` etwas (z. B. 1.5 → 2.0) oder senke `threshold_relative`.
- Bei stark schwankenden Sensorwerten hilft ein Sensor-Smoothing (in HA via Template/Statistics sensor).
- `clear_notification` funktioniert am zuverlässigsten, wenn die Companion App kürzlich geöffnet wurde (iOS Einschränkung).

---

## Lizenz

MIT

---

## Kontakt / Quellen

- Original-Author (angepasst) — Dein Blueprint (basierend auf Anfrage/Konversation).

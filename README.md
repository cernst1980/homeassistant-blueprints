# Home Assistant Blueprint – Raumlüftungsempfehlung (mit Meldungsbegrenzung)

## Funktionen
- Empfiehlt **Lüften**, **Fenster schließen** oder warnt bei **offenen Fenstern & Abwesenheit**.
- Nutzt relative/absolute Luftfeuchtigkeit und optional CO₂.
- **Meldungen überschreiben sich gegenseitig** (mobil & WebUI).
- Konfigurierbare Meldungsfrequenz (z. B. **max. 1x pro Tag**).

## Voraussetzungen
- Sensoren: relative LF, absolute LF innen/außen, optional CO₂
- (optional) Fenster-/Türsensoren
- (optional) Personen zur Anwesenheitserkennung
- **Zwei Helfer pro Raum:**
  - `input_text.lueften_status_<raum>`
  - `input_datetime.lueften_last_notify_<raum>`

## Installation
1. Blueprint importieren und speichern.
2. Pro Raum zwei Helfer anlegen:
   - **Helfer → Hinzufügen → Text → `lueften_status_<raum>`**
   - **Helfer → Hinzufügen → Datum/Zeit → `lueften_last_notify_<raum>`**
3. Automation erstellen und alle Eingaben ausfüllen.

## Hinweise
- Wenn sich der Status ändert (Lüften → Schließen → Warnung), wird **sofort benachrichtigt**.
- Wenn sich nichts ändert, wird **nur einmal pro Intervall** benachrichtigt (Standard: 24h).
- Alte Meldungen werden automatisch überschrieben.

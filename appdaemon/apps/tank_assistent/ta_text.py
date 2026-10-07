"""Deutsche Texte für Benachrichtigungen (Fallback, falls die KI nicht antwortet)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from ta_model import TZ

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def euro(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "–"
    return f"{value:.{digits}f}".replace(".", ",") + " €"


def money(value: float | None) -> str:
    return euro(value, 2)


def day_label(day: date, today: date) -> str:
    if day == today:
        return "heute"
    if day == today + timedelta(days=1):
        return "morgen"
    if day == today + timedelta(days=2):
        return "übermorgen"
    return f"{WEEKDAYS[day.weekday()]} {day.day}.{day.month}."


def when_label(dt: datetime, now: datetime) -> str:
    dt, now = dt.astimezone(TZ), now.astimezone(TZ)
    if dt <= now + timedelta(minutes=5):
        return "jetzt"
    return f"{day_label(dt.date(), now.date())} {dt.hour} Uhr"


def open_until_label(hour: int | None) -> str:
    if hour is None:
        return ""
    if hour == 0:
        return "offen bis Mitternacht"
    return f"offen bis {hour} Uhr"


def plan_message(plan, ctx: dict) -> tuple[str, str]:
    """Titel und Text zum aktuellen Plan.

    ctx: now, station_names, open_until (station->hour), tomorrow_km, tomorrow_label,
         tomorrow_ok, range_until (date|None), fuel_pct, fuel_l, discount_hint (bool)
    """
    now: datetime = ctx["now"]
    names = ctx["station_names"]
    best = plan.best
    lines: list[str] = []

    if plan.status == "unbekannt" or best is None:
        return "Tankplan", "Keine Planung möglich – es fehlen Preis- oder Tankdaten."

    station = names.get(best.station, best.station)
    hint = open_until_label(ctx.get("open_until", {}).get(best.station))
    where = f"{station}" + (f" ({hint})" if hint else "")

    if plan.status == "muss":
        title = "Heute tanken"
        reason = "Der Tank reicht nicht mehr bis zur nächsten günstigen Gelegenheit"
        if ctx.get("tomorrow_km", 0) >= 50 and not ctx.get("tomorrow_ok", True):
            reason = (f"Der Rest reicht nicht für morgen ({ctx.get('tomorrow_day', '')}, "
                      f"ca. {ctx['tomorrow_km']:.0f} km)")
        lines.append(f"{reason}.")
        lines.append(f"Am günstigsten: {where}, {when_label(best.start, now)}, "
                     f"erwartet ca. {euro(best.mu)}.")
    elif plan.status == "jetzt":
        title = "Jetzt tanken lohnt sich"
        lines.append(f"{names.get(plan.now_station, plan.now_station)}: {euro(plan.now_price)} "
                     f"– ca. {money(plan.now_advantage_eur)} günstiger als Abwarten.")
        if plan.guaranteed_until:
            lines.append(f"Der Preis kann bis {plan.guaranteed_until:%H:%M} Uhr nur noch fallen.")
    elif plan.status == "heute":
        title = f"Heute tanken, {best.start:%H} Uhr"
        lines.append(f"{where}: tanken, wenn der Preis bei höchstens {euro(_cap(best))} liegt "
                     f"(erwartet {euro(best.mu)}).")
    elif (best.start.date() - now.date()).days <= 2:
        title = "Noch nicht tanken"
        lines.append(f"Aus heutiger Sicht am besten {when_label(best.start, now)} bei {where}, "
                     f"wenn höchstens {euro(_cap(best))}.")
    else:
        title = "Kein Tanken nötig"
        lines.append(f"Richtwert: unter {euro(_cap(best))} lohnt sich Tanken. "
                     f"Der Plan wird täglich neu berechnet.")

    fuel_pct = ctx.get("fuel_pct")
    if fuel_pct is not None:
        tank = f"Tank {fuel_pct:.0f} % ({ctx.get('fuel_l', 0):.0f} l)"
        if ctx.get("range_until") and plan.status != "muss":
            tank += f", reicht bis einschließlich {day_label(ctx['range_until'], now.date()).rstrip('.')}"
        lines.append(tank + ".")
    if ctx.get("tomorrow_km", 0) >= 50 and plan.status != "muss":
        lines.append(f"Morgen ({ctx.get('tomorrow_day', '')}) ca. "
                     f"{ctx['tomorrow_km']:.0f} km erwartet – reicht.")
    if ctx.get("discount_hint"):
        lines.append("ADAC-Karte zeigen und an der Kasse zahlen.")
    return title, " ".join(lines)


def _cap(slot) -> float:
    """Zielpreis für die Anzeige: Reservationspreis, aber nie unter dem Erwartungswert."""
    if abs(slot.reservation) == float("inf"):
        return slot.mu
    return max(slot.reservation, slot.mu)


def refuel_message(refuel: dict) -> tuple[str, str]:
    title = f"Getankt: {refuel['liters']:.0f} l"
    text = f"{refuel['station_name']} für {euro(refuel['price_eff'])}"
    if refuel.get("saving_total") is not None:
        text += (f". Ersparnis gegenüber Durchschnitt: {money(refuel['saving_total'])} "
                 f"(Zeitpunkt {money(refuel['saving_timing'])}, Tankstelle "
                 f"{money(refuel['saving_station'])}, Rabatt {money(refuel['saving_discount'])})")
    if refuel.get("exploitation") is not None:
        text += f", {refuel['exploitation'] * 100:.0f} % des Möglichen"
    if refuel.get("source") == "geschaetzt":
        text += ". Tankstelle und Zeit geschätzt"
    return title, text + "."


def weekly_message(summary: dict, trend: str, plan_text: str) -> tuple[str, str]:
    month, year = summary.get("monat", {}), summary.get("jahr", {})
    text = (f"Preistrend: {trend}. Diesen Monat {month.get('tankvorgaenge', 0)}× getankt, "
            f"gespart {money(month.get('ersparnis'))}; dieses Jahr {money(year.get('ersparnis'))}.")
    if year.get("ausschoepfung") is not None:
        text += f" Ausschöpfung {year['ausschoepfung'] * 100:.0f} %."
    return "Tank-Wochenbilanz", text + " " + plan_text

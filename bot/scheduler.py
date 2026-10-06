"""Ранковий дайджест, вечірній підсумок, нагадування завчасно."""

import hashlib
from datetime import datetime, timedelta

from . import config, fmt, game, gcal, progress
from . import telegram as tg

RARITY = {"common": "звичайна", "rare": "рідкісна", "epic": "епічна", "legendary": "легендарна"}


def run_jobs(state, now: datetime):
    today, tomorrow = now.date(), now.date() + timedelta(days=1)
    events = gcal.list_events(today - timedelta(days=1), today + timedelta(days=14))

    _reminders(state, now, events)
    game.update_days(state, events, now)
    new = game.check_unlocks(state, today)
    if len(new) == 1:
        tg.send(f"🥚 <b>Нове яйце!</b>\nВсередині {RARITY[new[0]['rarity']]} істота. Відкрий ◐ Прогрес, щоб вилупити.", html=True)
    elif new:
        tg.send(f"🥚 <b>Нових яєць: {len(new)}</b>\nВідкрий ◐ Прогрес, щоб вилупити.", html=True)
    progress.publish(state, events, now)

    # GitHub cron неточний, тому «не раніше години X і ще не надсилали сьогодні»
    if config.MORNING_HOUR <= now.hour < config.MORNING_HOUR + 4 and _once(state, "morning", today):
        morning(state, today, fmt.for_day(events, today))
    if now.hour >= config.EVENING_HOUR and _once(state, "evening", today):
        evening(state, today, fmt.for_day(events, today), fmt.for_day(events, tomorrow))


def _once(state, kind, day):
    key = f"{kind}:{day.isoformat()}"
    if key in state["sent"]:
        return False
    state["sent"][key] = day.isoformat()
    return True


def done_buttons(state, events, day):
    rows = []
    for e in events[:10]:
        key = hashlib.md5(e["id"].encode()).hexdigest()[:10]
        title = e["title"][:40]
        state["btn"][key] = {"id": e["id"], "t": title, "d": day.isoformat()}
        mark = "✓" if e["id"] in state["done"] else "○"
        rows.append([(f"{mark} {title}", f"t:{key}")])
    return rows


def morning(state, today, events):
    text = f"<b>{fmt.day_title(today)}</b>\n\n{fmt.day_block(events)}"
    timed = [e for e in events if not e["all_day"]]
    if timed:
        text += f"\n\n{fmt.plural(len(events), 'справа', 'справи', 'справ')} · перша о {timed[0]['start']:%H:%M}"
    tg.send(text, buttons=done_buttons(state, events, today), html=True)


def evening(state, today, events, tomorrow_events):
    done = state["done"]
    n_done = sum(e["id"] in done for e in events)

    parts = []
    if events:
        parts.append(f"<b>Сьогодні · {n_done}/{len(events)}</b>\n{fmt.day_block(events, done)}")
    tomorrow = today + timedelta(days=1)
    parts.append(f"<b>Завтра · {fmt.day_title(tomorrow).lower()}</b>\n{fmt.day_block(tomorrow_events)}")
    if today.weekday() == 6:
        parts.append(week_stats(state, today))
    parts.append("Як пройшов день? Звіт — текстом або голосом.")

    open_items = [e for e in events if e["id"] not in done]
    tg.send("\n\n".join(parts), buttons=done_buttons(state, open_items, today), html=True)


def week_stats(state, today, days=7):
    planned = done = 0
    for i in range(days):
        d = state["days"].get((today - timedelta(days=i)).isoformat())
        if d:
            planned += d["planned"]
            done += d["done"]
    if not planned:
        return "Статистики ще немає."
    return f"<b>{days} днів</b> · {done}/{planned} · {round(100 * done / planned)}%"


def _reminders(state, now, events):
    for e in events:
        if e["id"] in state["done"] or e["id"] in state["reminded"]:
            continue
        if e["all_day"]:
            _deadline(state, now, e)
            continue
        lead = e["remind"] if e["remind"] is not None else config.REMIND_BEFORE_MIN
        mins = (e["start"] - now).total_seconds() / 60
        if lead > 0 and 0 < mins <= lead:
            state["reminded"][e["id"]] = now.date().isoformat()
            left = f"{int(mins)} хв" if mins < 90 else f"{mins / 60:.0f} год"
            tg.send(f"Через {left}\n{fmt.line(e)}", html=True)


def _deadline(state, now, e):
    """Дедлайни (весь день) з remind ≥ 1440 хв — нагадування за N днів, зранку."""
    lead_days = (e["remind"] or 0) // 1440
    days_left = (e["start"] - now.date()).days
    if lead_days and 0 < days_left <= lead_days and now.hour >= config.MORNING_HOUR:
        state["reminded"][e["id"]] = now.date().isoformat()
        left = "завтра" if days_left == 1 else f"через {days_left} дн"
        tg.send(f"Дедлайн {left} · {fmt.day_title(e['start']).lower()}\n{fmt.line(e)}", html=True)

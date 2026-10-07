"""Щоденні повідомлення (9:00 план · 15:00 що лишилось · 21:30 підсумок), нагадування, прострочення."""

import hashlib
from datetime import datetime, time, timedelta

from . import agent, config, finance, fmt, game, gcal, progress
from . import telegram as tg

RARITY = {"common": "звичайна", "rare": "рідкісна", "epic": "епічна", "legendary": "легендарна"}


def run_jobs(state, now: datetime):
    today, tomorrow = now.date(), now.date() + timedelta(days=1)
    events = gcal.list_events(today - timedelta(days=14), today + timedelta(days=14))

    deadlines = [e for e in gcal.list_deadlines(today - timedelta(days=30)) if e["id"] not in state["done"]]

    _reminders(state, now, events)
    game.update_days(state, events, now)
    late = agent.overdue(state, events, now)
    for e in late:
        game.on_overdue(state, e, today)

    new = game.check_unlocks(state, today)
    if len(new) == 1:
        tg.send(f"🥚 Нове яйце · {RARITY[new[0]['rarity']]} істота. Відкрий ◐ Прогрес.")
    elif new:
        tg.send(f"🥚 Нових яєць: {len(new)}. Відкрий ◐ Прогрес.")

    for text in finance.alerts(state, today):
        tg.send(text)

    t = now.time()
    todays = fmt.for_day(events, today)
    # GitHub cron неточний: «не раніше часу X, ще не надсилали сьогодні, і не надто пізно»
    if config.MORNING_TIME <= t < time(13) and _once(state, "morning", today):
        morning(state, now, todays, late, deadlines)
    if config.MIDDAY_TIME <= t < time(19) and _once(state, "midday", today):
        midday(state, now, todays)
    if t >= config.EVENING_TIME and _once(state, "evening", today):
        evening(state, now, todays, fmt.for_day(events, tomorrow))

    progress.publish(state, events, now, late, deadlines)


def _once(state, kind, day):
    key = f"{kind}:{day.isoformat()}"
    if key in state["sent"]:
        return False
    state["sent"][key] = day.isoformat()
    return True


def _key(state, e, day):
    key = hashlib.md5(e["id"].encode()).hexdigest()[:10]
    state["btn"][key] = {"id": e["id"], "t": e["title"][:36], "k": e["kind"], "d": day.isoformat()}
    return key


def toggle_buttons(state, events, day):
    rows = []
    for e in events[:14]:
        mark = "✓" if e["id"] in state["done"] else "○"
        em = fmt.GROUP_LABEL[e.get("group", "errands")].split()[0]
        rows.append([(f"{mark} {em} {e['title'][:34]}", f"t:{_key(state, e, day)}")])
    return rows


def action_buttons(state, events, day):
    """Для разових задач/дедлайнів: виконано / завтра (штраф) / скасувати (штраф)."""
    rows = []
    for e in events[:8]:
        k = _key(state, e, day)
        move = game.MOVE[e["kind"]] * (e.get("moves", 0) + 1)
        rows.append([(f"✓ {e['title'][:22]}", f"a:{k}:d"), (f"↷ завтра {fmt.signed(move)}", f"a:{k}:m"),
                     (f"✕ {fmt.signed(game.CANCEL[e['kind']])}", f"a:{k}:x")])
    return rows


def deadline_line(deadlines, today):
    parts = []
    for e in sorted(deadlines, key=fmt.ev_day)[:4]:
        n = (fmt.ev_day(e) - today).days
        when = "сьогодні" if n == 0 else f"{n} дн" if n > 0 else f"прострочено {-n} дн"
        parts.append(f"{fmt.escape(fmt.deadline_title(e['title']))} — {when}")
    return "⚑ " + " · ".join(parts) if parts else ""


def morning(state, now, events, late, deadlines=()):
    today = now.date()
    dl = deadline_line(deadlines, today)
    text = (f"{dl}\n\n" if dl else "") + f"<b>{fmt.day_title(today)}</b>\n{fmt.day_block(events, state['done'])}"
    if events:
        text += f"\n\n{fmt.plural(len(events), 'пункт', 'пункти', 'пунктів')} · до +{game.potential(events)} балів"
    shot = state["screen"].get((today - timedelta(days=1)).isoformat())
    if shot:
        text += f"\n📱 вчора {fmt.hm(shot['min'])}"
    text += "\n" + finance.short_line(state, today)
    tg.send(text, buttons=toggle_buttons(state, events, today), html=True)
    if late:
        tg.send("<b>⏰ Прострочено — що робимо?</b>\n" + "\n".join(
            f"· {fmt.escape(e['title'])} · з {fmt.short_date(fmt.ev_day(e))}" for e in late),
            buttons=action_buttons(state, late, today), html=True)


def midday(state, now, events):
    left = [e for e in events if e["id"] not in state["done"]]
    if not left:
        return
    today = now.date()
    tg.send(f"<b>Залишилось {len(left)} з {len(events)}</b> · сьогодні {fmt.signed(game.day_points(state, today))}\n"
            f"{fmt.day_block(left, state['done'])}",
            buttons=toggle_buttons(state, left, today), html=True)


def evening(state, now, events, tomorrow_events):
    today, done = now.date(), state["done"]
    n = sum(e["id"] in done for e in events)
    open_tasks = [e for e in events if e["kind"] != "habit" and e["id"] not in done]
    open_habits = [e for e in events if e["kind"] == "habit" and e["id"] not in done]

    parts = [f"<b>Підсумок · {n}/{len(events)} · {fmt.signed(game.day_points(state, today))} балів</b>\n"
             f"{fmt.day_block(events, done)}"]
    if open_habits:
        parts.append(f"Звички без ✓ до 04:00 = −5 кожна ({len(open_habits)} шт).")
    parts.append(f"<b>Завтра · {fmt.day_title(today + timedelta(days=1)).lower()}</b>\n"
                 f"{fmt.day_block(tomorrow_events)}")
    if today.weekday() == 6:
        parts.append(week_stats(state, today))
    parts.append(finance.day_report(state, today))
    if today.weekday() == 6:
        wr = finance.week_report(state, today)
        if wr:
            parts.append(wr)
    parts.append("Звіт — голосом або текстом.")
    tg.send("\n\n".join(parts), buttons=toggle_buttons(state, open_habits, today), html=True)
    if open_tasks:
        tg.send("<b>Не виконано — що робимо?</b>", buttons=action_buttons(state, open_tasks, today), html=True)


def week_stats(state, today, days=7):
    planned = done = 0
    for i in range(days):
        d = state["days"].get((today - timedelta(days=i)).isoformat())
        if d:
            planned += d["planned"]
            done += d["done"]
    pts = sum(game.day_points(state, today - timedelta(days=i)) for i in range(days))
    if not planned:
        return f"<b>{days} днів</b> · статистики ще немає"
    return f"<b>{days} днів</b> · {done}/{planned} · {round(100 * done / planned)}% · {fmt.signed(pts)} балів"


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
            tg.send(f"Через {left} · {fmt.escape(e['title'])}", html=True)


def _deadline(state, now, e):
    """Дедлайни (весь день) з remind ≥ 1440 хв — нагадування за N днів, зранку."""
    lead_days = (e["remind"] or 0) // 1440
    days_left = (e["start"] - now.date()).days
    if lead_days and 0 < days_left <= lead_days and now.time() >= config.MORNING_TIME:
        state["reminded"][e["id"]] = now.date().isoformat()
        left = "завтра" if days_left == 1 else f"через {fmt.plural(days_left, 'день', 'дні', 'днів')}"
        tg.send(f"⏳ Дедлайн {left} · {fmt.escape(e['title'])}", html=True)

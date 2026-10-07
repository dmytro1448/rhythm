import json
import sys
import time
from datetime import datetime, timedelta
from html import escape

from . import agent, config, finance, fmt, game, gcal, progress, scheduler, store
from . import telegram as tg

HELP = """<b>Ритм</b>
Голосом або текстом: звіт, нові задачі, дедлайни, перенесення, цілі.
Скрін екранного часу — просто надішли фото.

/today · /tomorrow · /week
/stats — прогрес · /score — правила балів
◐ Прогрес — застосунок: цілі, серії, істоти."""


def _err(e):
    return f"{type(e).__name__}: {e}" if config.DEBUG else type(e).__name__


def handle_message(msg, state):
    chat = msg["chat"]["id"]
    if not config.CHAT_ID:
        tg.send(f"Твій chat_id: <code>{chat}</code>\nДодай його в TELEGRAM_CHAT_ID.", html=True, chat_id=chat)
        return
    if chat != config.CHAT_ID:
        return

    now = datetime.now(config.TZ)
    if "web_app_data" in msg:
        web_app_data(msg["web_app_data"]["data"], state, now)
        return
    text = (msg.get("text") or msg.get("caption") or "").strip()
    if msg.get("photo"):
        tg.typing()
        info = agent.read_image(tg.download(msg["photo"][-1]["file_id"]))
        if info.get("type") == "screen" and info.get("minutes"):
            screen_shot(info, state, now, msg)
            if not text:
                return
        elif info.get("type") == "receipt" and info.get("total"):
            receipt(info, state, now)
            if not text:
                return
        else:
            text = f"[фото: {info.get('summary', 'без опису')}] {text}".strip()
    audio = msg.get("voice") or msg.get("audio") or msg.get("video_note")
    if audio:
        tg.typing()
        text = agent.transcribe(tg.download(audio["file_id"]))
        game.on_voice(state)
        tg.send(f"<i>«{escape(text)}»</i>", html=True)
    if not text:
        return

    if text.startswith("/"):
        command(text.split()[0].split("@")[0], state, now)
        return

    # Через затримку cron повідомлення може оброблятись пізніше, ніж надіслане
    sent = datetime.fromtimestamp(msg["date"], config.TZ)
    if now - sent > timedelta(minutes=3):
        text = f"[надіслано о {sent:%H:%M}] {text}"
    tg.typing()
    reply, used = agent.run(state, text, now)
    if used & {"mark_done", "add_log", "update_goal"}:
        game.on_report(state, now.date())
    tg.send(reply)
    if "make_meal_plan" in used and state.get("meal_plan"):
        tg.send(state["meal_plan"]["text"])
    _money_alerts(state, now)


def _money_alerts(state, now):
    for text in finance.alerts(state, now.date()):
        tg.send(text)


def receipt(info, state, now):
    """Чек → витрати по категоріях. Сума позицій підганяється під total."""
    day = now.date()
    try:
        day = datetime.strptime(info.get("date") or "", "%Y-%m-%d").date()
    except ValueError:
        pass
    total = round(float(info["total"]), 2)
    by_cat, last_cat = {}, None
    for it in info.get("items") or []:
        try:
            amount = float(it["amount"])
        except (TypeError, ValueError, KeyError):
            continue
        if amount < 0 and last_cat:  # знижка — до попередньої позиції, а не окремою витратою
            name, prev = by_cat[last_cat][-1]
            by_cat[last_cat][-1] = (name, prev + amount)
            continue
        last_cat = it.get("category", "other")
        by_cat.setdefault(last_cat, []).append((it.get("name", ""), amount))
    items_sum = sum(a for v in by_cat.values() for _, a in v)
    if not by_cat or abs(items_sum - total) > 0.05 * total:
        by_cat = {"food": [("покупки", total)]} if not by_cat else by_cat
        k = total / items_sum if items_sum else 1
        by_cat = {c: [(n, a * k) for n, a in v] for c, v in by_cat.items()}
    store_name = (info.get("store") or "чек")[:30]
    parts = []
    for cat, items in by_cat.items():
        amount = round(sum(a for _, a in items), 2)
        names = ", ".join(n for n, _ in items[:4])
        finance.add_expense(state, amount, cat, f"{store_name}: {names}", day, source="receipt")
        em, name = finance.CAT.get(cat, ("📦", "Інше"))
        parts.append(f"{em} {name} {finance.money(amount)}")
    tail = f"\nСьогодні: {finance.money(finance.period(state, now.date(), now.date())['total'])}"
    tg.send(f"🧾 {escape(store_name)} · {finance.money(total)}\n" + " · ".join(parts) + tail)
    _money_alerts(state, now)


def screen_shot(info, state, now, msg):
    sent = datetime.fromtimestamp(msg["date"], config.TZ).date()
    day = {"today": sent, "yesterday": sent - timedelta(days=1)}.get(info.get("day"))
    if day is None:
        try:
            day = datetime.strptime(info.get("day") or "", "%Y-%m-%d").date()
        except ValueError:
            day = sent
    mins = int(info["minutes"])
    prev = state["screen"].get((day - timedelta(days=1)).isoformat())
    game.on_screen(state, day, mins, info.get("apps"))
    line = f"📱 {fmt.hm(mins)} · {fmt.short_date(day)}"
    if prev:
        diff = mins - prev["min"]
        line += f" · {'↓' if diff < 0 else '↑'}{fmt.hm(abs(diff))}"
    lines = [line]
    apps = info.get("apps") or []
    if apps:
        lines.append(" · ".join(f"{escape(a['name'])} {fmt.hm(int(a['minutes']))}" for a in apps[:3]))
    tg.send("\n".join(lines), html=True)


def web_app_data(raw, state, now):
    """Зміни, збережені з міні-застосунку: {"done": {event_id: true/false}}"""
    data = json.loads(raw)
    changes = data.get("done", {})
    pts = sum(agent.set_done(state, [eid], bool(done), now) for eid, done in changes.items())
    if changes:
        tg.send(f"✓ Збережено з застосунку · {fmt.signed(pts)} балів")


def app_keyboard():
    url = progress.app_url()
    if not url:
        return None
    return {"keyboard": [[{"text": "◐ Прогрес", "web_app": {"url": url}}]],
            "resize_keyboard": True, "is_persistent": True}


def command(cmd, state, now):
    today = now.date()
    if cmd in ("/start", "/help"):
        kb = app_keyboard()
        tg.call("sendMessage", {"chat_id": config.CHAT_ID, "text": HELP, "parse_mode": "HTML",
                                **({"reply_markup": kb} if kb else {})})
        if kb:  # кнопка меню чату — лише в цьому приватному чаті, бо посилання містить ключ
            tg.call("setChatMenuButton", {"chat_id": config.CHAT_ID, "menu_button": {
                "type": "web_app", "text": "Прогрес", "web_app": {"url": progress.app_url()}}})
    elif cmd in ("/today", "/tomorrow"):
        d = today + timedelta(days=cmd == "/tomorrow")
        evs = fmt.for_day(gcal.list_events(d, d), d)
        tg.send(f"<b>{fmt.day_title(d)}</b>\n\n{fmt.day_block(evs, state['done'])}",
                buttons=scheduler.toggle_buttons(state, evs, today), html=True)
    elif cmd == "/week":
        evs = gcal.list_events(today, today + timedelta(days=6))
        blocks = [f"<b>{fmt.day_title(d)}</b>\n{fmt.day_block(fmt.for_day(evs, d), state['done'])}"
                  for d in (today + timedelta(days=i) for i in range(7))]
        tg.send("\n\n".join(blocks), html=True)
    elif cmd == "/score":
        tg.send(game.RULES, html=True)
    elif cmd == "/stats":
        p = state["stats"]
        lvl = game.level(p["xp"])
        tg.send(f"<b>Рівень {lvl}</b> · {p['xp']} балів · сьогодні {fmt.signed(game.day_points(state, today))} · "
                f"серія {game.current_streak(state, today)}\n"
                f"{scheduler.week_stats(state, today)}\n{scheduler.week_stats(state, today, 30)}\n"
                f"Істот: {len(state['unlocked'])}/{len(game.ROSTER)}", html=True)
    else:
        tg.send("Невідома команда. /help")


def handle_callback(cq, state):
    msg = cq.get("message") or {}
    data = cq.get("data", "")
    parts = data.split(":")
    entry = state["btn"].get(parts[1]) if len(parts) > 1 else None
    if msg.get("chat", {}).get("id") != config.CHAT_ID or not entry:
        _answer(cq)
        return
    now = datetime.now(config.TZ)
    eid, title = entry["id"], entry["t"]

    if parts[0] == "t":  # перемикач виконано/ні
        done = eid not in state["done"]
        pts = agent.set_done(state, [eid], done, now)
        label = f"{'✓' if done else '○'} {title}"
        _replace_row(msg, data, [{"text": label, "callback_data": data}])
        _answer(cq, f"{fmt.signed(pts)} балів")
        return

    op = parts[2]
    try:
        if op == "d":
            pts = agent.set_done(state, [eid], True, now)
            label = f"✓ {title} · {fmt.signed(pts)}"
        elif op == "m":
            _, pts = agent.move_event(state, eid, max(now.date(), game.cutoff(now)) + timedelta(days=1), now)
            label = f"↷ {title} → завтра · {fmt.signed(pts)}"
        else:
            _, pts = agent.cancel_event(state, eid, now)
            label = f"✕ {title} · {fmt.signed(pts)}"
    except agent.Refused as r:
        _answer(cq, str(r))
        return
    _replace_row(msg, data, [{"text": label, "callback_data": "n"}])
    _answer(cq, f"{fmt.signed(pts)} балів")


def _answer(cq, text=""):
    try:
        tg.call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": text})
    except Exception:
        pass  # запит міг застаріти, поки чекали cron


def _replace_row(msg, data, new_row):
    """Заміна рядка кнопок, у якому була натиснута кнопка."""
    markup = msg.get("reply_markup", {"inline_keyboard": []})
    rows = []
    for row in markup["inline_keyboard"]:
        hit = any(b.get("callback_data") == data for b in row)
        rows.append(new_row if hit else row)
    try:
        tg.call("editMessageReplyMarkup", {"chat_id": config.CHAT_ID, "message_id": msg["message_id"],
                                           "reply_markup": {"inline_keyboard": rows}})
    except Exception:
        pass


def run_once(poll=0):
    state = store.load()
    updates = tg.get_updates(state["offset"], poll)
    for u in updates:
        state["offset"] = u["update_id"] + 1
        try:
            if "callback_query" in u:
                handle_callback(u["callback_query"], state)
            elif "message" in u:
                handle_message(u["message"], state)
        except Exception as e:
            print("update failed:", _err(e))
            try:
                tg.send(f"Не вдалося обробити: {_err(e)}")
            except Exception:
                pass
    if config.CHAT_ID:
        try:
            scheduler.run_jobs(state, datetime.now(config.TZ))
        except Exception as e:
            print("jobs failed:", _err(e))
    changed = store.save(state)
    print(f"updates={len(updates)} state_changed={changed}")


def main():
    missing = [n for n in ("TELEGRAM_TOKEN", "OPENAI_API_KEY", "GOOGLE_SA_JSON") if not getattr(config, n)]
    if missing:
        sys.exit(f"Не задано: {', '.join(missing)}")
    if "--loop" in sys.argv:
        # Локальний режим: миттєві відповіді (довге опитування). Не запускай одночасно з GitHub.
        print("loop mode, Ctrl+C to stop")
        while True:
            try:
                run_once(poll=25)
            except Exception as e:
                print("loop error:", _err(e))
                time.sleep(5)
    else:
        run_once()

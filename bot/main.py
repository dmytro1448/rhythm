import json
import sys
import time
from datetime import datetime, timedelta
from html import escape

from . import agent, config, fmt, game, gcal, progress, scheduler, store
from . import telegram as tg

HELP = """<b>Ритм</b>

Пиши або говори — звіт, нові справи, перенесення.
Порядок справ — з Google Calendar.

/today — сьогодні
/tomorrow — завтра
/week — 7 днів
/stats — статистика

◐ Прогрес — твій застосунок: цілі, серії, колекція істот."""


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


def web_app_data(raw, state, now):
    """Зміни, збережені з міні-застосунку: {"done": {event_id: true/false}}"""
    data = json.loads(raw)
    changes = data.get("done", {})
    for eid, done in changes.items():
        agent.set_done(state, [eid], bool(done), now.date())
    if changes:
        n = sum(bool(v) for v in changes.values())
        tg.send(f"✓ Збережено з застосунку · {n} виконано" if n else "Збережено з застосунку")


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
    elif cmd in ("/today", "/tomorrow"):
        d = today + timedelta(days=cmd == "/tomorrow")
        evs = fmt.for_day(gcal.list_events(d, d), d)
        tg.send(f"<b>{fmt.day_title(d)}</b>\n\n{fmt.day_block(evs, state['done'])}",
                buttons=scheduler.done_buttons(state, evs, today), html=True)
    elif cmd == "/week":
        evs = gcal.list_events(today, today + timedelta(days=6))
        blocks = [f"<b>{fmt.day_title(d)}</b>\n{fmt.day_block(fmt.for_day(evs, d), state['done'])}"
                  for d in (today + timedelta(days=i) for i in range(7))]
        tg.send("\n\n".join(blocks), html=True)
    elif cmd == "/stats":
        p = state["stats"]
        lvl = game.level(p["xp"])
        tg.send(f"<b>Рівень {lvl}</b> · {p['xp']} XP · серія {game.current_streak(state, today)}\n"
                f"{scheduler.week_stats(state, today)}\n{scheduler.week_stats(state, today, 30)}\n"
                f"Істот: {len(state['unlocked'])}/{len(game.ROSTER)}", html=True)
    else:
        tg.send("Невідома команда. /help")


def handle_callback(cq, state):
    try:
        tg.call("answerCallbackQuery", {"callback_query_id": cq["id"]})
    except Exception:
        pass  # запит міг застаріти, поки чекали cron
    msg = cq.get("message") or {}
    data = cq.get("data", "")
    entry = state["btn"].get(data[2:]) if data.startswith("t:") else None
    if msg.get("chat", {}).get("id") != config.CHAT_ID or not entry:
        return

    done = entry["id"] not in state["done"]
    agent.set_done(state, [entry["id"]], done, datetime.now(config.TZ).date())

    markup = msg.get("reply_markup", {"inline_keyboard": []})
    for row in markup["inline_keyboard"]:
        for b in row:
            if b.get("callback_data") == data:
                b["text"] = f"{'✓' if done else '○'} {entry['t']}"
    tg.call("editMessageReplyMarkup", {"chat_id": config.CHAT_ID, "message_id": msg["message_id"],
                                       "reply_markup": markup})


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

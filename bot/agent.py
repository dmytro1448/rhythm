"""AI-агент: розуміє звіти (текст/голос), позначає виконане, керує календарем."""

import base64
import json
from datetime import date, datetime, timedelta
from functools import lru_cache

from openai import OpenAI

from . import config, fmt, game, gcal


@lru_cache
def _client():
    return OpenAI(api_key=config.OPENAI_API_KEY)


SCREEN_PROMPT = """Це скріншот? Якщо на ньому екранний час телефону (Screen Time / Digital Wellbeing),
поверни JSON: {"screen": true, "minutes": загальний час за день у хвилинах, "day": "today" | "yesterday" | "YYYY-MM-DD" | null,
"apps": [{"name": "...", "minutes": N}] до 5 найбільших}. Якщо це не екранний час — {"screen": false, "summary": "коротко, що на фото"}."""


def read_image(image: bytes) -> dict:
    url = "data:image/jpeg;base64," + base64.b64encode(image).decode()
    res = _client().chat.completions.create(
        model=config.OPENAI_MODEL, response_format={"type": "json_object"},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": SCREEN_PROMPT},
            {"type": "image_url", "image_url": {"url": url, "detail": "low"}},
        ]}],
    )
    return json.loads(res.choices[0].message.content)


def transcribe(audio: bytes, filename="voice.ogg") -> str:
    res = _client().audio.transcriptions.create(
        model=config.TRANSCRIBE_MODEL, file=(filename, audio), language=config.TRANSCRIBE_LANGUAGE
    )
    return res.text.strip()


def _fn(name, description, props, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": props, "required": list(required)},
    }}


_DATE = {"type": "string", "description": "YYYY-MM-DD"}
_TIME = {"type": "string", "description": "HH:MM, 24 год"}

TOOLS = [
    _fn("get_events", "Справи з календаря за період (включно).",
        {"from_date": _DATE, "to_date": _DATE}, ["from_date", "to_date"]),
    _fn("create_event", "Створити справу в календарі. Без start_time — справа на весь день (дедлайн).", {
        "title": {"type": "string"},
        "date": _DATE,
        "start_time": _TIME,
        "end_time": _TIME,
        "duration_min": {"type": "integer"},
        "description": {"type": "string"},
        "recurrence": {"type": "string", "description": "RRULE для регулярних справ, напр. FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=12"},
        "remind_before_min": {"type": "integer", "description": "За скільки хвилин нагадати (0 — не нагадувати, 1440 — за добу)"},
    }, ["title", "date"]),
    _fn("update_event", "Змінити/перенести справу. Вказуй лише поля, що змінюються.", {
        "event_id": {"type": "string"}, "title": {"type": "string"}, "date": _DATE,
        "start_time": _TIME, "end_time": _TIME, "description": {"type": "string"},
        "remind_before_min": {"type": "integer"},
    }, ["event_id"]),
    _fn("delete_event", "Видалити справу. Лише на явне прохання користувача. series=true — прибрати всю регулярну серію (напр. «знайшов роботу — прибери пошук роботи»).",
        {"event_id": {"type": "string"}, "series": {"type": "boolean"}}, ["event_id"]),
    _fn("log_screen_time", "Записати екранний час телефону за день.",
        {"minutes": {"type": "integer"}, "date": _DATE}, ["minutes", "date"]),
    _fn("mark_done", "Позначити справи виконаними.",
        {"event_ids": {"type": "array", "items": {"type": "string"}}}, ["event_ids"]),
    _fn("unmark_done", "Зняти позначку виконання.",
        {"event_ids": {"type": "array", "items": {"type": "string"}}}, ["event_ids"]),
    _fn("add_goal", "Додати глобальну ціль місяця з вимірюваним результатом.", {
        "title": {"type": "string"},
        "target": {"type": "integer", "description": "Скільки одиниць треба досягти"},
        "unit": {"type": "string", "description": "Одиниця: разів, сторінок, км, грн…"},
        "emoji": {"type": "string", "description": "Один емодзі-символ цілі"},
        "match": {"type": "string", "description": "Слова через кому: справи календаря з такою назвою автоматично додають +1"},
    }, ["title", "target", "unit"]),
    _fn("update_goal", "Оновити прогрес цілі (add — додати, set — встановити) або змінити її.", {
        "goal_id": {"type": "string"}, "add": {"type": "number"}, "set": {"type": "number"},
        "title": {"type": "string"}, "target": {"type": "integer"},
    }, ["goal_id"]),
    _fn("delete_goal", "Видалити ціль. Лише на явне прохання.", {"goal_id": {"type": "string"}}, ["goal_id"]),
    _fn("add_log", "Зберегти нотатку зі звіту: самопочуття, енергія, інсайти, проблеми, дії поза календарем.", {
        "text": {"type": "string", "description": "Стисло, 1–2 речення"},
        "energy": {"type": "integer", "description": "Енергія 1–5, якщо зрозуміло зі звіту"},
    }, ["text"]),
]

SYSTEM = """Ти — особистий асистент ритму життя в Telegram. Мова — українська.
Стиль — мінімалізм: 1–5 коротких рядків, без води, без мотиваційних фраз, емодзі лише ✓ та ·.

Зараз: {now}.

Джерело правди про справи — Google Calendar. Порядок справ бери саме звідти, не вигадуй справ, яких там немає.

Справи — це переважно «пункти дня» без часу (подія на весь день). Звіт за вчора теж можна приймати: вчорашні пункти є нижче.
Екранний час: користувач надсилає скріни або пише цифру — фіксуй через log_screen_time. Мета — менше телефону.

Як працюєш:
1. Звіт. Користувач розповідає, що зробив — зістав зі справами календаря (по суті, не дослівно) і виклич mark_done. Важливе поза календарем (самопочуття, енергія, інсайти, перешкоди, незаплановані дії) збережи через add_log.
2. Невиконане — коротко запропонуй, куди перенести (найближчий вільний слот). Переносиш лише після згоди або якщо користувач сам попросив.
3. Цілі місяця. Якщо у звіті є прогрес по цілі (прочитав 30 сторінок, пробіг 5 км, відклав 1000 грн) — update_goal з add. Справи календаря, що збігаються з match цілі, рахуються автоматично — не дублюй.
4. Планування. Додаєш/переносиш/змінюєш справи в календарі. Для звичок — recurrence. Якщо час не вказано — обери вільний слот і назви його. Перед додаванням на інший день спершу подивись get_events, щоб не було накладок.
5. Видаляєш лише на явне прохання.
6. Після дій — коротке підтвердження, що саме зроблено.

Вчора:
{yesterday_events}

Сьогодні ({today}):
{today_events}

Завтра:
{tomorrow_events}

Цілі місяця:
{goals}

Останні нотатки:
{log}"""


def _system(state, now):
    today, tomorrow = now.date(), now.date() + timedelta(days=1)
    events = gcal.list_events(today - timedelta(days=1), tomorrow)
    done = state["done"]

    def block(d):
        evs = fmt.for_day(events, d)
        return "\n".join(fmt.plain(e, done) for e in evs) or "(нічого)"

    goals = "\n".join(f"[{g['id']}] {g['title']}: {g['progress']}/{g['target']} {g['unit']}"
                      f"{' (auto: ' + g['match'] + ')' if g.get('match') else ''}"
                      for g in state["goals"]) or "(немає)"
    log = "\n".join(f"{x['date']} {x['text']}" for x in state["log"][-8:]) or "(немає)"
    return SYSTEM.format(
        now=f"{fmt.WEEKDAYS[now.weekday()]}, {now:%Y-%m-%d %H:%M} ({config.TZ.key})",
        today=today.isoformat(), today_events=block(today),
        tomorrow_events=block(tomorrow), log=log, goals=goals,
        yesterday_events=block(today - timedelta(days=1)),
    )


def _ev(e, done):
    d = e["start"] if e["all_day"] else e["start"].date()
    return {"id": e["id"], "title": e["title"], "date": d.isoformat(), "time": fmt.when(e),
            "done": e["id"] in done, "description": e["description"][:200]}


def _d(s):
    return date.fromisoformat(s) if s else None


def set_done(state, ids, done, today):
    for eid in ids:
        if (eid in state["done"]) == done:
            continue
        if done:
            state["done"][eid] = today.isoformat()
        else:
            state["done"].pop(eid, None)
        game.on_done(state, gcal.set_done(eid, done), done)


def _exec(name, a, state, now):
    today = now.date()
    if name == "get_events":
        return [_ev(e, state["done"]) for e in gcal.list_events(_d(a["from_date"]), _d(a["to_date"]))]
    if name == "create_event":
        rec = [a["recurrence"]] if a.get("recurrence") else None
        e = gcal.create_event(a["title"], _d(a["date"]), a.get("start_time"), a.get("end_time"),
                              a.get("duration_min"), a.get("description", ""), rec, a.get("remind_before_min"))
        return _ev(e, state["done"])
    if name == "update_event":
        e = gcal.update_event(a["event_id"], a.get("title"), _d(a.get("date")), a.get("start_time"),
                              a.get("end_time"), a.get("description"), a.get("remind_before_min"))
        return _ev(e, state["done"])
    if name == "delete_event":
        gcal.delete_event(a["event_id"], bool(a.get("series")))
        state["done"].pop(a["event_id"], None)
        return {"ok": True}
    if name in ("mark_done", "unmark_done"):
        set_done(state, a["event_ids"], name == "mark_done", today)
        return {"ok": True}
    if name == "add_goal":
        gid = f"g{len(state['goals']) + 1}"
        while any(g["id"] == gid for g in state["goals"]):
            gid += "x"
        g = {"id": gid, "title": a["title"], "target": int(a["target"]), "unit": a["unit"],
             "emoji": a.get("emoji", ""), "match": a.get("match", ""), "progress": 0}
        state["goals"].append(g)
        return g
    if name in ("update_goal", "delete_goal"):
        g = next((g for g in state["goals"] if g["id"] == a["goal_id"]), None)
        if not g:
            return {"error": "no such goal"}
        if name == "delete_goal":
            state["goals"].remove(g)
            return {"ok": True}
        if a.get("set") is not None:
            g["progress"] = a["set"]
        if a.get("add"):
            g["progress"] += a["add"]
        for k in ("title", "target"):
            if a.get(k):
                g[k] = a[k]
        return {**g, "pct": game.goal_pct(g)}
    if name == "log_screen_time":
        game.on_screen(state, _d(a["date"]), a["minutes"])
        return {"ok": True}
    if name == "add_log":
        entry = {"date": today.isoformat(), "time": f"{now:%H:%M}", "text": a["text"]}
        if a.get("energy"):
            entry["energy"] = a["energy"]
        state["log"].append(entry)
        return {"ok": True}
    return {"error": f"unknown tool {name}"}


def _model_params():
    # gpt-5* — reasoning-моделі: без temperature, мінімальні міркування = дешевше і швидше
    if config.OPENAI_MODEL.startswith("gpt-5"):
        return {"reasoning_effort": "minimal"}
    return {"temperature": 0.3}


def run(state, text, now: datetime):
    """Повертає (відповідь, множина викликаних інструментів)."""
    messages = [{"role": "system", "content": _system(state, now)}, *state["history"][-16:],
                {"role": "user", "content": text}]
    reply, used = "Готово.", set()
    for _ in range(8):
        msg = _client().chat.completions.create(
            model=config.OPENAI_MODEL, messages=messages, tools=TOOLS, **_model_params(),
        ).choices[0].message
        if not msg.tool_calls:
            reply = (msg.content or reply).strip()
            break
        messages.append({"role": "assistant", "content": msg.content,
                         "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            used.add(tc.function.name)
            try:
                result = _exec(tc.function.name, json.loads(tc.function.arguments or "{}"), state, now)
            except Exception as e:
                result = {"error": f"{type(e).__name__}: {e}"}
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result, ensure_ascii=False, default=str)})
    state["history"] += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
    return reply, used

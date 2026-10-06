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
    _fn("create_event", "Створити справу. Без start_time — пункт дня. deadline=true — обовʼязкова задача з дедлайном (+40 балів, дорогі перенесення).", {
        "title": {"type": "string"},
        "date": _DATE,
        "start_time": _TIME,
        "end_time": _TIME,
        "duration_min": {"type": "integer"},
        "description": {"type": "string"},
        "recurrence": {"type": "string", "description": "RRULE для регулярних справ, напр. FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=12"},
        "remind_before_min": {"type": "integer", "description": "За скільки хвилин нагадати (0 — не нагадувати, 1440 — за добу, 10080 — за тиждень)"},
        "deadline": {"type": "boolean"},
    }, ["title", "date"]),
    _fn("update_event", "Змінити/перенести справу. Перенесення на пізнішу дату коштує балів; звички переносити не можна. Вказуй лише поля, що змінюються.", {
        "event_id": {"type": "string"}, "title": {"type": "string"}, "date": _DATE,
        "start_time": _TIME, "end_time": _TIME, "description": {"type": "string"},
        "remind_before_min": {"type": "integer"},
    }, ["event_id"]),
    _fn("delete_event", "Скасувати справу (штраф: задача −5, дедлайн −25). Лише на явне прохання. series=true — прибрати всю регулярну серію без штрафу (напр. «знайшов роботу — прибери пошук роботи»).",
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
        "match": {"type": "string", "description": "Слова через кому: справи календаря з такою назвою автоматично додають прогрес"},
        "per": {"type": "number", "description": "Скільки одиниць додає одна виконана справа з match (за замовчуванням 1)"},
        "screen_max": {"type": "integer", "description": "Для цілей екранного часу: ліміт хвилин на день; прогрес = дні в межах ліміту"},
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

SYSTEM = """Ти — асистент ритму життя в Telegram. Мова — українська.
Відповідай максимально конкретно й коротко: 1–3 рядки. Без вступів, привітань, порад і мотивації, якщо не просять. Без markdown.
Дати пиши як «8 жов», не ISO. Формати відповідей (бали — лише ті, що реально нараховані інструментами):
виконано: «✓ Розтяжка, Прес · +20»
перенесено: «↷ Звіт → 8 жов · −5»
додано: «+ Подати документи · 15 жов · дедлайн» (без балів)
скасовано: «✕ Звіт · −5»
питання: «<повна назва задачі>: перенести на 8 жов (−5) чи скасувати (−5)?»
Не дописуй загальну суму балів у відповідь на звіт — лише бали за конкретні дії.
Не вигадуй бонусів: ідеальний день, серія і штрафи за пропуски нараховуються автоматично о 04:00 — не згадуй їх у відповіді на звіт.
звичку просять перенести: «Звички не переносяться. Сьогодні ще можна зробити — інакше −5 о 04:00.»

Зараз: {now}.
Бали сьогодні: {points} (на питання про бали — бери лише це число й журнал нижче, не рахуй сам).
Журнал балів сьогодні:
{ledger}

Джерело правди — Google Calendar. Не вигадуй справ, яких там немає.
Типи: habit — щоденна звичка, task — разова задача, deadline — обовʼязкова з дедлайном.

Правила:
1. Звіт (текст/голос) → зістав зі справами по суті й виклич mark_done. Самопочуття, енергію, інсайти, перешкоди → add_log. Звіт за вчора теж приймай.
2. Звички (habit) не переносяться ніколи. Невиконана звичка = пропуск, −5 о 04:00.
3. Невиконані/прострочені task і deadline — НЕ переносиш сам. Питаєш, що робити, з ціною: «перенести на <дата> (−N) / скасувати (−N)?». Дієш лише після відповіді.
4. Нові справи з голосу/тексту → create_event. Обовʼязкове з кінцевою датою → deadline=true. Регулярне → recurrence. Без часу → пункт дня.
5. Екранний час (цифра або скрін) → log_screen_time. Прогрес по цілях → update_goal (add); справи з match цілі рахуються самі.
6. Видаляєш лише на явне прохання.

Бали: звичка +10, задача +15, дедлайн +40 (із запізненням +10/+20); пропуск звички −5; перенесення задачі −5×№, дедлайну −10×№; прострочення −5/−15 щодня; скасування −5/−25; ідеальний день +30; звіт +10.

Прострочено:
{overdue}

Вчора:
{yesterday_events}

Сьогодні ({today}):
{today_events}

Завтра:
{tomorrow_events}

Цілі:
{goals}

Нотатки:
{log}"""


def overdue(state, events, now):
    last = game.cutoff(now)
    return [e for e in events if e["kind"] != "habit" and fmt.ev_day(e) < last and e["id"] not in state["done"]]


def _system(state, now):
    today, tomorrow = now.date(), now.date() + timedelta(days=1)
    events = gcal.list_events(today - timedelta(days=14), tomorrow)
    done = state["done"]

    def block(d):
        evs = fmt.for_day(events, d)
        return "\n".join(fmt.plain(e, done) for e in evs) or "(нічого)"

    goals = "\n".join(f"[{g['id']}] {g['title']}: {g['progress']}/{g['target']} {g['unit']}"
                      f"{' (auto: ' + g['match'] + ')' if g.get('match') else ''}"
                      for g in state["goals"]) or "(немає)"
    log = "\n".join(f"{x['date']} {x['text']}" for x in state["log"][-8:]) or "(немає)"
    od = "\n".join(f"{fmt.plain(e, done)} · з {fmt.ev_day(e).isoformat()}" for e in overdue(state, events, now)) or "(немає)"
    return SYSTEM.format(
        now=f"{fmt.WEEKDAYS[now.weekday()]}, {now:%Y-%m-%d %H:%M} ({config.TZ.key})",
        points=fmt.signed(game.day_points(state, today)),
        ledger="\n".join(f"{fmt.signed(x['p'])} {x['w']}" for x in state["ledger"] if x["d"] == today.isoformat()) or "(порожньо)",
        today=today.isoformat(), today_events=block(today), overdue=od,
        tomorrow_events=block(tomorrow), log=log, goals=goals,
        yesterday_events=block(today - timedelta(days=1)),
    )


def _ev(e, done):
    d = e["start"] if e["all_day"] else e["start"].date()
    return {"id": e["id"], "title": e["title"], "date": d.isoformat(), "time": fmt.when(e),
            "kind": e["kind"], "moves": e.get("moves", 0),
            "done": e["id"] in done, "description": e["description"][:200]}


def _d(s):
    return date.fromisoformat(s) if s else None


def set_done(state, ids, done, now):
    total = 0
    for eid in ids:
        if (eid in state["done"]) == done:
            continue
        ev = gcal.set_done(eid, done) or gcal.get_event(eid)
        if done:
            state["done"][eid] = now.date().isoformat()
        else:
            state["done"].pop(eid, None)
        before = state["stats"]["xp"]
        game.on_done(state, ev, done, now)
        total += state["stats"]["xp"] - before
    return total


class Refused(Exception):
    pass


def move_event(state, eid, new_day, now, start_time=None, end_time=None):
    """Перенесення зі штрафом. Повертає (подія, штраф)."""
    cur = gcal.get_event(eid)
    pts = 0
    if new_day and new_day != fmt.ev_day(cur):
        if cur["kind"] == "habit":
            raise Refused("Щоденні звички не переносяться.")
        props = None
        if new_day > fmt.ev_day(cur):
            n, pts = game.on_move(state, cur, now.date())
            props = {"moves": n}
        return gcal.update_event(eid, day=new_day, start_time=start_time, end_time=end_time, props=props), pts
    return gcal.update_event(eid, start_time=start_time, end_time=end_time), 0


def cancel_event(state, eid, now, series=False):
    cur = gcal.get_event(eid)
    pts = 0 if series else game.on_cancel(state, cur, now.date())
    gcal.delete_event(eid, series)
    state["done"].pop(eid, None)
    return cur, pts


def _exec(name, a, state, now):
    today = now.date()
    if name == "get_events":
        return [_ev(e, state["done"]) for e in gcal.list_events(_d(a["from_date"]), _d(a["to_date"]))]
    if name == "create_event":
        rec = [a["recurrence"]] if a.get("recurrence") else None
        e = gcal.create_event(a["title"], _d(a["date"]), a.get("start_time"), a.get("end_time"),
                              a.get("duration_min"), a.get("description", ""), rec, a.get("remind_before_min"),
                              deadline=bool(a.get("deadline")))
        return _ev(e, state["done"])
    if name == "update_event":
        try:
            e, pts = move_event(state, a["event_id"], _d(a.get("date")), now, a.get("start_time"), a.get("end_time"))
        except Refused as r:
            return {"error": str(r)}
        if any(a.get(k) is not None for k in ("title", "description", "remind_before_min")):
            e = gcal.update_event(a["event_id"], a.get("title"), description=a.get("description"),
                                  remind_before_min=a.get("remind_before_min"))
        return {**_ev(e, state["done"]), "points": pts}
    if name == "delete_event":
        e, pts = cancel_event(state, a["event_id"], now, bool(a.get("series")))
        return {"ok": True, "title": e["title"], "points": pts}
    if name in ("mark_done", "unmark_done"):
        return {"ok": True, "points": set_done(state, a["event_ids"], name == "mark_done", now)}
    if name == "add_goal":
        gid = f"g{len(state['goals']) + 1}"
        while any(g["id"] == gid for g in state["goals"]):
            gid += "x"
        g = {"id": gid, "title": a["title"], "target": int(a["target"]), "unit": a["unit"],
             "emoji": a.get("emoji", ""), "match": a.get("match", ""), "progress": 0}
        if a.get("per"):
            g["per"] = a["per"]
        if a.get("screen_max"):
            g.update(screen_max=int(a["screen_max"]), **{"from": today.isoformat()})
            game.refresh_goals(state)
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
    return {"temperature": 0.2}


ACTION_MARKS = {"✓": {"mark_done"}, "↷": {"update_event"}, "✕": {"delete_event"}, "+ ": {"create_event", "add_goal"}}


def _claimed_without_tool(reply, used):
    for mark, tools in ACTION_MARKS.items():
        if any(line.lstrip().startswith(mark) for line in reply.splitlines()) and not tools & used:
            return mark.strip()
    return None


def run(state, text, now: datetime):
    """Повертає (відповідь, множина викликаних інструментів)."""
    fresh = (f"Актуально зараз: бали сьогодні {fmt.signed(game.day_points(state, now.date()))}, "
             f"усього {state['stats']['xp']}. Числа з попередніх відповідей застаріли.")
    messages = [{"role": "system", "content": _system(state, now)}, *state["history"][-16:],
                {"role": "system", "content": fresh}, {"role": "user", "content": text}]
    reply, used, checked = "Готово.", set(), False
    for _ in range(9):
        msg = _client().chat.completions.create(
            model=config.OPENAI_MODEL, messages=messages, tools=TOOLS, **_model_params(),
        ).choices[0].message
        if not msg.tool_calls:
            reply = (msg.content or reply).strip()
            claimed = _claimed_without_tool(reply, used)
            if claimed and not checked:
                # Модель «підтвердила» дію, не виконавши її — змушуємо виконати або виправити відповідь
                checked = True
                messages += [{"role": "assistant", "content": reply},
                             {"role": "system", "content": f"Ти написав про дію ({claimed}), але не викликав інструмент. "
                              "Виклич потрібний інструмент зараз. Якщо дія не потрібна — дай виправлену відповідь без цієї позначки."}]
                continue
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

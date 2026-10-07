"""AI-агент: розуміє звіти (текст/голос), позначає виконане, керує календарем."""

import base64
import json
from datetime import date, datetime, timedelta
from functools import lru_cache

from openai import OpenAI

from . import config, finance, fmt, game, gcal


@lru_cache
def _client():
    return OpenAI(api_key=config.OPENAI_API_KEY)


IMAGE_PROMPT = """Визнач, що на зображенні, і поверни JSON.
1) Екранний час телефону (Screen Time / Digital Wellbeing):
{"type": "screen", "minutes": загальний час за день у хвилинах, "day": "today" | "yesterday" | "YYYY-MM-DD" | null,
 "apps": [{"name": "...", "minutes": N}] до 5 найбільших}
2) Чек / квитанція / підтвердження оплати:
{"type": "receipt", "store": "назва", "date": "YYYY-MM-DD" | null, "currency": "€", "total": сума до сплати,
 "items": [{"name": "коротко українською", "amount": ціна з урахуванням знижок, "category": "food|cafe|transport|home|health|comm|fun|housing|other"}]}
   Сума amount усіх items має дорівнювати total (знижки розподіли по товарах). Продукти й кафе — food, засоби гігієни/побутова хімія — home.
3) Інше: {"type": "other", "summary": "коротко, що на фото"}"""


def read_image(image: bytes) -> dict:
    url = "data:image/jpeg;base64," + base64.b64encode(image).decode()
    res = _client().chat.completions.create(
        model=config.OPENAI_MODEL, response_format={"type": "json_object"},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": IMAGE_PROMPT},
            {"type": "image_url", "image_url": {"url": url, "detail": "high"}},
        ]}],
    )
    return json.loads(res.choices[0].message.content)


VOICE_HINT = ("Українська мова. Звіт про справи й витрати: розтяжка, прес, тренування, FatSecret, пайтон, "
              "англійська, читання, Shopify, пошук роботи, проїзний, SIM-картка, євро, чек.")


def transcribe(audio: bytes, filename="voice.ogg") -> str:
    def run(model):
        return _client().audio.transcriptions.create(
            model=model, file=(filename, audio), language=config.TRANSCRIBE_LANGUAGE, prompt=VOICE_HINT,
        ).text.strip()

    text = run(config.TRANSCRIBE_MODEL)
    if not _looks_ukrainian(text):  # модель «зісковзнула» в іншу мову чи латиницю — друга спроба
        text = run("whisper-1")
    return text


def _looks_ukrainian(text):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return True
    cyr = sum("а" <= c.lower() <= "я" or c.lower() in "іїєґ" for c in letters)
    foreign = sum(c.lower() in "ыэъёў" for c in letters)
    return cyr / len(letters) > 0.7 and not foreign


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
        "group": {"type": "string", "enum": ["regime", "body", "learn", "work", "errands"],
                  "description": "Група: regime — сон/режим, body — тіло/спорт/їжа, learn — навчання, work — робота/гроші/проєкти, errands — побутові справи"},
    }, ["title", "date", "group"]),
    _fn("update_event", "Змінити/перенести справу. Перенесення на пізнішу дату коштує балів; звички переносити не можна. Вказуй лише поля, що змінюються.", {
        "event_id": {"type": "string"}, "title": {"type": "string"}, "date": _DATE,
        "start_time": _TIME, "end_time": _TIME, "description": {"type": "string"},
        "remind_before_min": {"type": "integer"},
        "deadline": {"type": "boolean", "description": "true — зробити задачу обовʼязковою (дедлайн)"},
    }, ["event_id"]),
    _fn("delete_event", "Скасувати справу (штраф: задача −5, дедлайн −25). Лише на явне прохання. series=true — прибрати всю регулярну серію без штрафу (напр. «знайшов роботу — прибери пошук роботи»).",
        {"event_id": {"type": "string"}, "series": {"type": "boolean"},
         "replaced": {"type": "boolean", "description": "true — задачу замінює щойно створена обовʼязкова справа з тим самим змістом; без штрафу"}},
        ["event_id"]),
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
    _fn("add_expense", "Записати витрату. Кілька покупок різних категорій — окремими викликами.", {
        "amount": {"type": "number"},
        "category": {"type": "string", "enum": finance.CAT_KEYS,
                     "description": "food — продукти й напої з магазину (вода, чай, хліб…), cafe — лише їжа/напої в закладі (ресторан, фастфуд, кавʼярня), transport, home — побут/гігієна, health, comm — звʼязок, fun — дозвілля, housing — житло, other"},
        "note": {"type": "string", "description": "Що саме, коротко"},
        "date": _DATE,
    }, ["amount", "category"]),
    _fn("delete_expense", "Видалити помилкову витрату за id.", {"expense_id": {"type": "string"}}, ["expense_id"]),
    _fn("expense_report", "Звіт про витрати за період: сума, по категоріях, середнє за день.",
        {"from_date": _DATE, "to_date": _DATE}, ["from_date", "to_date"]),
    _fn("make_meal_plan", "Скласти раціон і список покупок на тиждень на вказану суму (окремий агент). Лише на прохання.",
        {"weekly_amount": {"type": "number"}}, ["weekly_amount"]),
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
додано: «+ Купити проїзний · 7 жов» або «+ Подати документи · 9 жов · дедлайн» (позначка «дедлайн» — лише якщо deadline=true; без балів)
скасовано: «✕ Звіт · −5»
питання: «<повна назва задачі>: перенести на 8 жов (−5) чи скасувати (−5)?»
Не дописуй загальну суму балів у відповідь на звіт — лише бали за конкретні дії.
Не вигадуй бонусів: ідеальний день, серія і штрафи за пропуски нараховуються автоматично о 04:00 — не згадуй їх у відповіді на звіт.
звичку просять перенести: «Звички не переносяться. Сьогодні ще можна зробити — інакше −5 о 04:00.»

Зараз: {now}.
Найближчі дати: {calendar}
Бали сьогодні: {points} (на питання про бали — бери лише це число й журнал нижче, не рахуй сам).
Журнал балів сьогодні:
{ledger}

Джерело правди — Google Calendar. Не вигадуй справ, яких там немає.
Типи: habit — щоденна звичка, task — разова задача, deadline — обовʼязкова з дедлайном.

Правила:
1. Звіт (текст/голос) → зістав зі справами по суті й виклич mark_done. Самопочуття, енергію, інсайти, перешкоди → add_log. Звіт за вчора теж приймай.
2. Звички (habit) не переносяться ніколи. Невиконана звичка = пропуск, −5 о 04:00.
   Прохання перенести звичку («перенеси пайтон на завтра») → відповідай лише про цю звичку: «Звички не переносяться. Сьогодні ще можна зробити — інакше −5 о 04:00.» Не питай про інші справи.
3. Невиконані/прострочені task і deadline — НЕ переносиш сам. Питаєш, що робити, з ціною: «перенести на <дата> (−N) / скасувати (−N)?». Дієш лише після відповіді.
4. Нові справи з голосу/тексту → create_event з правильною group. Не створюй справу, якщо така вже є в календарі на цю дату. У звіті фраза на кшталт «пайтон завтра» про щоденну звичку означає лише «сьогодні не зробив» — нічого не створюй і не переноси. Обовʼязкове з кінцевою датою → deadline=true. Регулярне → recurrence. Без часу → пункт дня.
5. Екранний час (цифра або скрін) → log_screen_time. Прогрес по цілях → update_goal (add); справи з match цілі рахуються самі.
6. Видаляєш лише на явне прохання.
7. «Обовʼязково», «до пʼятниці», «кров з носа» → нова справа з deadline=true на кінцеву дату (create_event). Якщо в найближчі дні вже є разова задача (task) з тим самим змістом — прибери її (delete_event replaced=true, без штрафу). Не відповідай «вже є». Назву бери зі слів користувача. Відповідь: «+ <назва> · до <дата> · дедлайн».
8. mark_done — ЛИШЕ коли користувач прямо каже, що вже зробив. Нова справа ніколи не позначається виконаною.

Витрати (бюджету немає — лише облік і звіти):
- Будь-яка згадка про покупку/оплату → add_expense (сума, категорія, що саме), кожна покупка окремо. Відповідь: «💶 −8,90 € · Кафе · бургер» і в кінці «Сьогодні: 35,70 €».
- Питання про витрати за період → expense_report. Відповідай сумою, топ-категоріями і середнім за день, 1–3 рядки.
- Раціон — лише якщо просять і називають суму на тиждень → make_meal_plan.
Витрати: {money}

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


def _money_line(state, today):
    st = finance.status(state, today)
    if not st:
        return "ще нічого не записано"
    recent = "; ".join(f"[{e['id']}] {e['d'][5:]} {e['amount']} {e['cat']} {e['note']}" for e in state["expenses"][-6:])
    return (f"сьогодні {finance.money(st['today']['total'])}, тиждень {finance.money(st['week']['total'])}, "
            f"місяць {finance.money(st['month']['total'])}, у середньому {finance.money(st['avg_day'])}/день. "
            f"Останні: {recent}")


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
        calendar=", ".join(f"{fmt.WEEKDAYS[(today + timedelta(days=i)).weekday()]} = {(today + timedelta(days=i)).isoformat()}"
                           for i in range(1, 8)),
        points=fmt.signed(game.day_points(state, today)),
        money=_money_line(state, today),
        ledger="\n".join(f"{fmt.signed(x['p'])} {x['w']}" for x in state["ledger"] if x["d"] == today.isoformat()) or "(порожньо)",
        today=today.isoformat(), today_events=block(today), overdue=od,
        tomorrow_events=block(tomorrow), log=log, goals=goals,
        yesterday_events=block(today - timedelta(days=1)),
    )


def _stem(title):
    words = [w for w in "".join(c if c.isalnum() else " " for c in title.lower()).split() if len(w) >= 4]
    return words[0][:5] if words else title.lower()[:5]


def _existing_twin(title, day):
    """Назва справи, що вже стоїть цього дня і починається з того ж ключового слова (захист від дублікатів)."""
    stem = _stem(title)
    for e in fmt.for_day(gcal.list_events(day, day), day):
        if _stem(e["title"]) == stem:
            return e["title"]
    return None


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
        twin = _existing_twin(a["title"], _d(a["date"]))
        if twin and not a.get("recurrence"):
            return {"error": f"Вже є в календарі на цю дату: «{twin}». Нічого не створено."}
        rec = [a["recurrence"]] if a.get("recurrence") else None
        e = gcal.create_event(a["title"], _d(a["date"]), a.get("start_time"), a.get("end_time"),
                              a.get("duration_min"), a.get("description", ""), rec, a.get("remind_before_min"),
                              deadline=bool(a.get("deadline")), group=a.get("group"))
        out = _ev(e, state["done"])
        if a.get("deadline"):
            # Разові задачі до дедлайну — щоб агент прибрав ту, яку новий дедлайн замінює (напр. «Тренування» ≈ «спортзал»)
            span = [x for x in gcal.list_events(today, _d(a["date"]))
                    if x["kind"] == "task" and x["id"] != e["id"] and x["id"] not in state["done"]]
            if span:
                out["open_tasks_until_deadline"] = [{"id": x["id"], "title": x["title"], "date": fmt.ev_day(x).isoformat()} for x in span]
                out["hint"] = ("Прибери задачу з open_tasks_until_deadline (delete_event replaced=true) лише якщо вона ПОВНІСТЮ означає те саме, "
                               "що новий дедлайн (напр. «Тренування» = «сходити в спортзал»). Якщо стара задача містить щось ще "
                               "(напр. «проїзний і SIM-картка», а новий дедлайн лише про проїзний) — НЕ чіпай її.")
        return out
    if name == "update_event":
        try:
            e, pts = move_event(state, a["event_id"], _d(a.get("date")), now, a.get("start_time"), a.get("end_time"))
        except Refused as r:
            return {"error": str(r)}
        if any(a.get(k) is not None for k in ("title", "description", "remind_before_min", "deadline")):
            e = gcal.update_event(a["event_id"], a.get("title"), description=a.get("description"),
                                  remind_before_min=a.get("remind_before_min"),
                                  props={"kind": "deadline"} if a.get("deadline") else None)
        return {**_ev(e, state["done"]), "points": pts}
    if name == "delete_event":
        e, pts = cancel_event(state, a["event_id"], now, bool(a.get("series") or a.get("replaced")))
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
    if name == "add_expense":
        e = finance.add_expense(state, a["amount"], a["category"], a.get("note", ""), _d(a.get("date")) or today)
        t = finance.period(state, today, today)
        return {"ok": True, "expense": e, "today_total": t["total"]}
    if name == "delete_expense":
        return {"ok": finance.delete_expense(state, a["expense_id"])}
    if name == "expense_report":
        r = finance.period(state, _d(a["from_date"]), _d(a["to_date"]))
        return {**r, "items": [e for e in state["expenses"] if a["from_date"] <= e["d"] <= a["to_date"]][-30:]}
    if name == "make_meal_plan":
        finance.make_meal_plan(_client(), config.OPENAI_MODEL, state, float(a["weekly_amount"]))
        return {"ok": True, "note": "Раціон надіслано окремим повідомленням."}
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
    reply, used, checked = "Не вийшло виконати — повтори, будь ласка, інакше.", set(), False
    for _ in range(9):
        msg = _client().chat.completions.create(
            model=config.OPENAI_MODEL, messages=messages, tools=TOOLS, **_model_params(),
        ).choices[0].message
        if not msg.tool_calls:
            reply = (msg.content or "").strip() or reply
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

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
2) Чек / квитанція:
{"type": "receipt", "store": "назва магазину з чека", "date": "YYYY-MM-DD" | null, "total": підсумок ДО СПЛАТИ (рядок KOPĀ / SUMMA / Total / Kopā apmaksai),
 "items": [{"raw": "назва позиції ДОСЛІВНО як надруковано", "name": "коротко українською", "amount": сума рядка,
            "category": "food|cafe|transport|home|health|comm|fun|housing|other"}]}
   ПРАВИЛА: переписуй лише те, що реально надруковано, нічого не вигадуй і не вгадуй. Нечитабельний рядок — пропусти.
   Знижки (Atlaide, Akcija, -x.xx) — окремими items з відʼємною сумою. Кількість×ціну не перемножуй сам — бери суму рядка.
   Продукти/напої з магазину — food, гігієна/побутова хімія — home.
3) Інше: {"type": "other", "summary": "коротко, що на фото"}"""


def read_image(image: bytes, careful=False) -> dict:
    url = "data:image/jpeg;base64," + base64.b64encode(image).decode()
    prompt = IMAGE_PROMPT + ("\nЦе ПОВТОРНЕ прочитання: користувач каже, що минулого разу були помилки. "
                             "Перевір кожен рядок і підсумок особливо уважно." if careful else "")
    res = _client().chat.completions.create(
        model=config.VISION_MODEL, response_format={"type": "json_object"}, temperature=0,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
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
    _fn("delete_expense", "Видалити витрату за id, або весь чек — за його rid.", {"expense_id": {"type": "string"}}, ["expense_id"]),
    _fn("reread_receipt", "Ще раз уважно прочитати фото останнього чека і перезаписати його позиції (коли користувач каже, що чек прочитано неправильно).", {}),
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
8. «Замість X додай Y» → прибери X на ту дату (delete_event replaced=true, без штрафу) і створи Y.
9. «Прибери X взагалі / назавжди / з усіх днів» про звичку → delete_event series=true (без штрафу).
10. «Перенеси дедлайн» → update_event з новою датою. Ніколи не видаляй і не створюй заново.
11. mark_done — ЛИШЕ коли користувач прямо каже, що вже зробив. Нова справа ніколи не позначається виконаною.

Витрати (бюджету немає — лише облік і звіти):
- Будь-яка згадка про покупку/оплату → add_expense (сума, категорія, що саме), кожна покупка окремо. Відповідь: «💶 −8,90 € · Кафе · бургер» і в кінці «Сьогодні: 35,70 €».
- Питання про витрати за період → expense_report. Відповідай сумою, топ-категоріями і середнім за день, 1–3 рядки.
- Чек: позиції бери ТІЛЬКИ з «Останній чек» нижче, ніколи не вигадуй. «Неправильно прочитав чек / подивись ще раз» → reread_receipt. «Видали чек» → delete_expense з rid чека.
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
            f"Останні: {recent}" + _last_receipt_line(state))


def _last_receipt_line(state):
    r = state.get("last_receipt")
    if not r:
        return ""
    items = "; ".join(f"{x['name']} {x['amount']}" for x in r["items"][:20])
    return f"\nОстанній чек (rid={r['rid']}): {r['store']} {r['d']}, разом {r['total']}: {items}"


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


_done_titles = []


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
        _done_titles.append(ev["title"])
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


FOREVER_WORDS = ("взагалі", "назавжди", "з усіх днів", "з усіх наступних", "в принципі", "повністю", "зовсім", "з розкладу")
_user_text = ""


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
        # «прибери взагалі / назавжди / з усіх днів» про звичку — уся серія, без штрафу (модель часто забуває series)
        series = bool(a.get("series")) or (any(w in _user_text.lower() for w in FOREVER_WORDS)
                                            and gcal.get_event(a["event_id"])["kind"] == "habit")
        e, pts = cancel_event(state, a["event_id"], now, series or bool(a.get("replaced")))
        if series and e["kind"] == "habit":  # звичку прибрано назавжди — прибираємо й ціль, що її рахувала
            low = e["title"].lower()
            state["goals"] = [g for g in state["goals"]
                              if not (g.get("match") and any(m.strip().lower() in low for m in g["match"].split(",") if m.strip()))]
        return {"ok": True, "title": e["title"], "points": pts, "series": series}
    if name in ("mark_done", "unmark_done"):
        _done_titles.clear()
        pts = set_done(state, a["event_ids"], name == "mark_done", now)
        return {"ok": True, "points": pts, "titles": list(_done_titles)}
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
        return {"ok": True, "expense": e, "today_total": t["total"], "today": today.isoformat()}
    if name == "delete_expense":
        gone = [e for e in state["expenses"] if e["id"] == a["expense_id"] or e.get("rid") == a["expense_id"]]
        for e in gone:
            finance.delete_expense(state, e["id"])
        return {"ok": bool(gone), "deleted": gone}
    if name == "reread_receipt":
        return reread_receipt(state, now)
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


CAT_NAME = {k: n for k, (_, n) in finance.CAT.items()}


def record_receipt(state, info, now, file_id=None):
    """Чек → окремі витрати по позиціях (спільний rid). Повертає текст для користувача."""
    import uuid
    day = now.date()
    try:
        day = date.fromisoformat(info.get("date") or "")
    except ValueError:
        pass
    store_name = (info.get("store") or "чек")[:30]
    rid = "r" + uuid.uuid4().hex[:7]
    items = []
    for it in info.get("items") or []:
        try:
            amount = round(float(it["amount"]), 2)
        except (TypeError, ValueError, KeyError):
            continue
        items.append((it.get("name") or it.get("raw") or "позиція", it.get("raw", ""), amount, it.get("category", "other")))
    total = round(float(info.get("total") or sum(x[2] for x in items)), 2)
    for name, raw, amount, cat in items:
        e = finance.add_expense(state, amount, cat, f"{store_name}: {name}", day, source="receipt")
        e["rid"], e["raw"] = rid, raw[:40]
    diff = round(total - sum(x[2] for x in items), 2)
    if abs(diff) >= 0.01:
        e = finance.add_expense(state, diff, "other", f"{store_name}: коригування до суми чека", day, source="receipt")
        e["rid"] = rid
    state["last_receipt"] = {"rid": rid, "file_id": file_id, "store": store_name, "d": day.isoformat(), "total": total,
                             "items": [{"name": n, "raw": r, "amount": a, "cat": c} for n, r, a, c in items], "diff": diff}
    lines = [f"🧾 {store_name} · {finance.money(total)} · {fmt.short_date(day)}"]
    lines += [f"· {n} — {finance.money(a)}" for n, _, a, _ in items[:25]]
    if abs(diff) >= 0.01:
        lines.append(f"⚠️ Позиції дають {finance.money(total - diff)}, а підсумок чека {finance.money(total)} — "
                     f"різницю {finance.money(diff)} записав окремо. Якщо щось не так — напиши «перечитай чек».")
    return "\n".join(lines)


def reread_receipt(state, now):
    from . import telegram as tg
    last = state.get("last_receipt")
    if not last or not last.get("file_id"):
        return {"error": "Немає фото останнього чека — надішли його ще раз."}
    for e in [e for e in state["expenses"] if e.get("rid") == last["rid"]]:
        finance.delete_expense(state, e["id"])
    info = read_image(tg.download(last["file_id"]), careful=True)
    if info.get("type") != "receipt":
        return {"error": "Не вдалося прочитати чек — надішли фото рівніше й ближче."}
    return {"ok": True, "summary": record_receipt(state, info, now, last["file_id"])}


def describe(name, a, r):
    """Рядок для користувача про РЕАЛЬНО виконану дію (або помилку). None — нічого показувати."""
    if not isinstance(r, dict):
        return None
    if r.get("error"):
        return f"· {r['error']}"
    if name == "create_event":
        return f"+ {r['title']} · {fmt.short_date(_d(r['date']))}" + (" · дедлайн" if r.get("kind") == "deadline" else "")
    if name == "update_event":
        pts = r.get("points") or 0
        return f"↷ {r['title']} → {fmt.short_date(_d(r['date']))}" + (f" · {fmt.signed(pts)}" if pts else "")
    if name == "delete_event":
        return f"✕ {r['title']}" + (" — з усіх днів" if r.get("series") else "") + (f" · {fmt.signed(r['points'])}" if r.get("points") else "")
    if name in ("mark_done", "unmark_done") and r.get("titles"):
        mark = "✓" if name == "mark_done" else "↺"
        return f"{mark} {', '.join(r['titles'])} · {fmt.signed(r['points'])}"
    if name == "add_expense":
        e = r["expense"]
        when = "" if e["d"] == r.get("today") else f" · {fmt.short_date(_d(e['d']))}"
        return f"💶 −{finance.money(e['amount'])} · {CAT_NAME.get(e['cat'], 'Інше')} · {e['note']}{when}".replace("−−", "−")
    if name == "delete_expense" and r.get("deleted"):
        return "🗑 " + ", ".join(f"{e['note'] or e['cat']} {finance.money(e['amount'])}" for e in r["deleted"])
    if name == "log_screen_time":
        return f"📱 {fmt.hm(int(a['minutes']))} · {fmt.short_date(_d(a['date']))}"
    if name == "add_goal":
        return f"🎯 + {r['title']} · {r['target']} {r['unit']}"
    if name == "update_goal" and r.get("title"):
        return f"🎯 {r['title']}: {r['progress']}/{r['target']} {r['unit']} · {r['pct']}%"
    if name == "delete_goal":
        return "🎯 ціль прибрано"
    if name == "reread_receipt" and r.get("summary"):
        return r["summary"]
    return None


CLAIM_WORDS = ("видал", "перенес", "додано", "додав", "записав", "записано", "позначив", "позначено", "прибрав",
               "прибрано", "скасова", "оновив", "оновлено", "змінив", "змінено")


def _claims_action(text):
    low = text.lower()
    if any(w in low for w in CLAIM_WORDS):
        return True
    return any(line.lstrip().startswith(m) for line in text.splitlines() for m in ("✓", "✕", "↷", "💶", "+ ", "🗑"))


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
    """Повертає (відповідь, множина викликаних інструментів).
    Підтвердження дій формує КОД з фактичних результатів — модель не може «вдати» дію."""
    fresh = (f"Актуально зараз: бали сьогодні {fmt.signed(game.day_points(state, now.date()))}, "
             f"усього {state['stats']['xp']}. Числа з попередніх відповідей застаріли.")
    messages = [{"role": "system", "content": _system(state, now)}, *state["history"][-12:],
                {"role": "system", "content": fresh}, {"role": "user", "content": text}]
    global _user_text
    _user_text = text
    used, actions, text_reply, retried, spent_today = set(), [], "", False, False
    for _ in range(10):
        msg = _client().chat.completions.create(
            model=config.OPENAI_MODEL, messages=messages, tools=TOOLS, **_model_params(),
        ).choices[0].message
        if not msg.tool_calls:
            text_reply = (msg.content or "").strip()
            if not actions and _claims_action(text_reply) and not retried:
                retried = True
                messages += [{"role": "assistant", "content": text_reply},
                             {"role": "system", "content": "Ти описав дію, але не викликав жодного інструмента — нічого не змінилось. "
                              "Виклич потрібні інструменти зараз. Якщо не зрозуміло, що робити, — постав одне коротке уточнювальне питання."}]
                continue
            break
        messages.append({"role": "assistant", "content": msg.content,
                         "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            used.add(tc.function.name)
            args = json.loads(tc.function.arguments or "{}")
            try:
                result = _exec(tc.function.name, args, state, now)
            except Exception as e:
                result = {"error": f"не вдалося ({type(e).__name__})"}
            if tc.function.name == "add_expense" and isinstance(result, dict) and result.get("expense", {}).get("d") == now.date().isoformat():
                spent_today = True
            line = describe(tc.function.name, args, result)
            if line:
                actions.append(line)
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result, ensure_ascii=False, default=str)})

    if actions:
        reply = "\n".join(actions)
        if spent_today:
            reply += f"\nСьогодні: {finance.money(finance.period(state, now.date(), now.date())['total'])}"
        if "?" in text_reply:  # уточнювальне питання моделі — додаємо
            reply += "\n\n" + text_reply
    elif text_reply and not _claims_action(text_reply):
        reply = text_reply
    elif text_reply and "?" in text_reply:
        reply = text_reply
    else:
        reply = "Нічого не змінено. Скажи конкретніше: що саме зробити і на коли."
    state["history"] += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
    return reply, used

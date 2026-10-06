from datetime import date
from html import escape  # noqa: F401 — використовується як fmt.escape

WEEKDAYS = ["понеділок", "вівторок", "середа", "четвер", "пʼятниця", "субота", "неділя"]
MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня",
          "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]


def day_title(d: date):
    return f"{WEEKDAYS[d.weekday()].capitalize()}, {d.day} {MONTHS[d.month - 1]}"


def on_day(e, d: date):
    if e["all_day"]:
        return e["start"] <= d < e["end"]
    return e["start"].date() == d


def ev_day(e) -> date:
    return e["start"] if e["all_day"] else e["start"].date()


def for_day(events, d: date):
    return sorted((e for e in events if on_day(e, d)), key=sort_key)


def when(e):
    if e["all_day"]:
        return "весь день"
    s, end = e["start"], e["end"]
    if end.date() == s.date() and end > s:
        return f"{s:%H:%M}–{end:%H:%M}"
    return f"{s:%H:%M}"


# Групи справ у порядку показу. Ключові слова задають і групу, і порядок усередині неї.
GROUPS = [
    ("regime", "🌅", "Режим", ["підйом", "прокин", "відбій", "сон"]),
    ("body", "🏃", "Тіло", ["розтяж", "прес", "тренуван", "спорт", "біг", "fatsecret", "їжа", "харч"]),
    ("learn", "📚", "Навчання", ["python", "пайтон", "англ", "читан", "книг", "курс", "урок"]),
    ("work", "💼", "Робота і гроші", ["shopify", "магазин", "робот", "ваканс", "відгук", "бюджет", "витрат"]),
    ("errands", "📋", "Справи", []),
]
GROUP_KEYS = [g[0] for g in GROUPS]
GROUP_LABEL = {k: f"{em} {name}" for k, em, name, _ in GROUPS}


def classify(title: str, kind: str, explicit: str = ""):
    """(група, порядок у групі). Явна група з календаря має пріоритет."""
    low = title.lower()
    for key, _, _, words in GROUPS:
        for i, w in enumerate(words):
            if w in low:
                return (explicit or key), i
    return (explicit or "errands"), 99


def line(e, done_ids=None):
    mark = "· "
    if done_ids is not None:
        mark = "✓ " if e["id"] in done_ids else "○ "
    flag = "⚑ " if e.get("kind") == "deadline" else ""
    if e["all_day"]:
        return f"{mark}{flag}{escape(e['title'])}"
    return f"{mark}{flag}{escape(e['title'])} <code>{when(e)}</code>"


def sort_key(e):
    """Групи по порядку → дедлайни першими → порядок ключових слів → час → назва."""
    return (GROUP_KEYS.index(e.get("group", "errands")), e.get("kind") != "deadline", e.get("rank", 99),
            e["start"].isoformat() if not e["all_day"] else "", e["title"])


def day_block(events, done_ids=None):
    if not events:
        return "<i>вільний день</i>"
    out, cur = [], None
    for e in sorted(events, key=sort_key):
        g = e.get("group", "errands")
        if g != cur:
            if cur is not None:
                out.append("")
            done = sum(x["id"] in done_ids for x in events if x.get("group", "errands") == g) if done_ids is not None else None
            total = sum(1 for x in events if x.get("group", "errands") == g)
            out.append(f"<b>{GROUP_LABEL[g]}</b>" + (f" · {done}/{total}" if done is not None else ""))
            cur = g
        out.append(line(e, done_ids))
    return "\n".join(out)


def plain(e, done_ids):
    done = " ✓" if e["id"] in done_ids else ""
    kind = {"habit": "звичка", "task": "задача", "deadline": "ДЕДЛАЙН"}[e["kind"]]
    t = "" if e["all_day"] else f" {when(e)}"
    return f"[{e['id']}] {kind}{t} — {e['title']}{done}"


def hm(minutes):
    return f"{minutes // 60} год {minutes % 60:02d} хв" if minutes >= 60 else f"{minutes} хв"


def plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def short_date(d: date):
    return f"{d.day} {MONTHS[d.month - 1][:3]}"


def deadline_title(title: str) -> str:
    t = title
    for p in ("ДЕДЛАЙН · ", "ДЕДЛАЙН: ", "ДЕДЛАЙН "):
        if t.upper().startswith(p.upper()):
            t = t[len(p):]
    return t[:1].upper() + t[1:]


def signed(n: int) -> str:
    return f"+{n}" if n > 0 else f"−{abs(n)}" if n < 0 else "0"

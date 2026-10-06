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


def line(e, done_ids=None):
    mark = "· "
    if done_ids is not None:
        mark = "✓ " if e["id"] in done_ids else "○ "
    if e["all_day"]:
        return f"{mark}{escape(e['title'])}"
    return f"{mark}<code>{when(e)}</code>  {escape(e['title'])}"


def sort_key(e):
    """Спершу справи з часом, потім пункти дня."""
    return (e["all_day"], e["start"].isoformat() if not e["all_day"] else "", e["title"])


def day_block(events, done_ids=None):
    if not events:
        return "<i>вільний день</i>"
    return "\n".join(line(e, done_ids) for e in events)


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


def signed(n: int) -> str:
    return f"+{n}" if n > 0 else f"−{abs(n)}" if n < 0 else "0"

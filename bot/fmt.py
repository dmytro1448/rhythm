from datetime import date
from html import escape

WEEKDAYS = ["понеділок", "вівторок", "середа", "четвер", "пʼятниця", "субота", "неділя"]
MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня",
          "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]


def day_title(d: date):
    return f"{WEEKDAYS[d.weekday()].capitalize()}, {d.day} {MONTHS[d.month - 1]}"


def on_day(e, d: date):
    if e["all_day"]:
        return e["start"] <= d < e["end"]
    return e["start"].date() == d


def for_day(events, d: date):
    return [e for e in events if on_day(e, d)]


def when(e):
    if e["all_day"]:
        return "весь день"
    s, end = e["start"], e["end"]
    if end.date() == s.date() and end > s:
        return f"{s:%H:%M}–{end:%H:%M}"
    return f"{s:%H:%M}"


def line(e, done_ids=None):
    mark = ""
    if done_ids is not None:
        mark = "✓ " if e["id"] in done_ids else "· "
    return f"{mark}<code>{when(e)}</code>  {escape(e['title'])}"


def day_block(events, done_ids=None):
    if not events:
        return "<i>вільний день</i>"
    return "\n".join(line(e, done_ids) for e in events)


def plain(e, done_ids):
    done = " ✓" if e["id"] in done_ids else ""
    d = e["start"] if e["all_day"] else e["start"].date()
    return f"[{e['id']}] {d.isoformat()} {when(e)} {e['title']}{done}"


def plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"

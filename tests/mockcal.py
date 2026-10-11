"""In-memory календар, що підміняє bot.gcal у тестах."""
import itertools
from datetime import datetime, timedelta

from bot import config, fmt, gcal

TZ = config.TZ
DB = {}
_id = itertools.count(1)


def add(title, day, kind="habit", time=None, moves=0, remind=None, group=None):
    i = f"ev{next(_id)}"
    if time:
        s = datetime.combine(day, datetime.strptime(time, "%H:%M").time(), TZ)
        e, ad = s + timedelta(minutes=30), False
    else:
        s, e, ad = day, day + timedelta(days=1), True
    g, r = fmt.classify(title, kind, group or "")
    DB[i] = dict(id=i, title=title, start=s, end=e, all_day=ad, description="", remind=remind,
                 kind=kind, moves=moves, group=g, rank=r)
    return i


def list_events(a, b, query=None):
    return [dict(e) for e in DB.values() if a <= fmt.ev_day(e) <= b]


def list_deadlines(first, days=120):
    return [dict(e) for e in DB.values() if e["kind"] == "deadline" and first <= fmt.ev_day(e) <= first + timedelta(days=days)]


def get_event(i):
    return dict(DB[i])


def set_done(i, d):
    return dict(DB[i])


def update_event(i, title=None, day=None, start_time=None, end_time=None, description=None,
                 remind_before_min=None, props=None):
    e = DB[i]
    if title:
        e["title"] = title
    if day:
        if e["all_day"]:
            e["start"], e["end"] = day, day + timedelta(days=1)
        else:
            e["start"] = datetime.combine(day, e["start"].timetz())
            e["end"] = e["start"] + timedelta(minutes=30)
    if props:
        if "moves" in props:
            e["moves"] = int(props["moves"])
        if props.get("kind") == "deadline" and e["kind"] != "habit":
            e["kind"] = "deadline"
    return dict(e)


def delete_event(i, series=False):
    t = DB[i]
    if series and t["kind"] == "habit":
        for k in [k for k, e in DB.items() if e["kind"] == "habit" and e["title"] == t["title"]]:
            DB.pop(k)
    else:
        DB.pop(i)


def create_event(title, day, start_time=None, end_time=None, duration_min=None, description="",
                 recurrence=None, remind_before_min=None, source=None, deadline=False, group=None):
    kind = "habit" if recurrence else "deadline" if deadline else "task"
    return dict(DB[add(title, day, kind, start_time, remind=remind_before_min, group=group)])


for _n in ("list_events", "list_deadlines", "get_event", "set_done", "update_event", "delete_event", "create_event"):
    setattr(gcal, _n, globals()[_n])

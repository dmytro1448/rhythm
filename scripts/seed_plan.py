"""Заливає місячний план з plan.yaml у Google Calendar.

    python scripts/seed_plan.py            # показати, що буде створено
    python scripts/seed_plan.py --apply    # створити події
    python scripts/seed_plan.py --clear    # видалити все, що створив цей скрипт
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bot import game, gcal, store  # noqa: E402

SOURCE = "plan"
DAYS = {"mon": "MO", "tue": "TU", "wed": "WE", "thu": "TH", "fri": "FR", "sat": "SA", "sun": "SU"}
PY_DAYS = list(DAYS)


def load(path):
    plan = yaml.safe_load(Path(path).read_text())
    start, end = plan["start"], plan["end"]
    events = []
    for r in plan.get("routines", []):
        first_day = r.get("from", start)
        # UNTIL: для подій на весь день — дата, для подій з часом — UTC-час
        until = end.strftime("%Y%m%d") if not r.get("time") else gcal.rrule_until(end)
        if r.get("every"):
            first = first_day
            rule = f"FREQ=DAILY;INTERVAL={r['every']};UNTIL={until}"
        else:
            days = r.get("days", PY_DAYS)
            first = next(first_day + timedelta(days=i) for i in range(7)
                         if PY_DAYS[(first_day + timedelta(days=i)).weekday()] in days)
            rule = f"FREQ=WEEKLY;BYDAY={','.join(DAYS[d] for d in days)};UNTIL={until}"
        events.append(dict(title=r["title"], day=first, start_time=r.get("time"),
                           duration_min=r.get("duration"), description=r.get("note", ""),
                           recurrence=[rule], remind_before_min=r.get("remind")))
    for t in plan.get("tasks", []):
        events.append(dict(title=t["title"], day=t["date"], start_time=t.get("time"),
                           duration_min=t.get("duration"), description=t.get("note", ""),
                           remind_before_min=t.get("remind"), deadline=bool(t.get("deadline"))))
    return start, end, events, plan.get("goals", [])


def seed_goals(goals, start):
    state = store.load()
    state["goals"] = []
    for i, g in enumerate(goals, 1):
        item = {"id": f"g{i}", "title": g["title"], "target": g["target"], "unit": g["unit"],
                "emoji": g.get("emoji", ""), "match": g.get("match", ""), "progress": 0}
        for k in ("per", "screen_max"):
            if g.get(k):
                item[k] = g[k]
        if g.get("screen_max"):
            item["from"] = start.isoformat()
        state["goals"].append(item)
    game.refresh_goals(state)
    store.save(state)
    print(f"цілей у стані: {len(state['goals'])}")


def main():
    path = Path(__file__).resolve().parent.parent / "plan.yaml"
    start, end, events, goals = load(path)
    if "--goals" in sys.argv:
        seed_goals(goals, start)
        return

    if "--clear" in sys.argv:
        old = gcal.list_events(start - timedelta(days=7), end + timedelta(days=7),
                               query={"privateExtendedProperty": f"source={SOURCE}", "singleEvents": False,
                                      "orderBy": None})
        for e in old:
            gcal.delete_event(e["id"])
        print(f"видалено {len(old)}")
        return

    for e in events:
        rec = f"  [{e['recurrence'][0].split(';UNTIL')[0]}]" if e.get("recurrence") else ""
        print(f"{e['day']} {e['start_time'] or 'весь день':>9}  {e['title']}{rec}")
    if "--apply" not in sys.argv:
        print(f"\n{len(events)} подій. Запусти з --apply, щоб створити.")
        return
    for e in events:
        gcal.create_event(source=SOURCE, **e)
    print(f"створено {len(events)}")


if __name__ == "__main__":
    main()

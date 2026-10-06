"""Бали, рівні, серії, цілі, яйця з істотами.

Кожна зміна балів пишеться в журнал (ledger) з причиною — прогрес фіксується прозоро.
"""

import math
import random
from datetime import date, datetime, timedelta

from . import fmt

# ---- система балів
DONE = {"habit": 10, "task": 15, "deadline": 40}  # виконано вчасно
DONE_LATE = {"habit": 10, "task": 10, "deadline": 20}  # виконано після свого дня
MISS_HABIT = -5  # звичка не відмічена до 04:00 наступного дня
MOVE = {"task": -5, "deadline": -10}  # × номер перенесення: −5, −10, −15…
OVERDUE = {"task": -5, "deadline": -15}  # за кожен день прострочення
CANCEL = {"task": -5, "deadline": -25, "habit": -5}
PERFECT = 30  # усі пункти дня виконані
REPORT = 10  # звіт за день (раз на день)
SCREEN = 5  # зафіксовано екранний час за день
STREAK_DAY, STREAK_MAX = 2, 20  # бонус серії: 2 × днів, не більше 20
CLOSED_PCT = 70  # день «закрито» для серії, якщо виконано ≥ 70%
DAY_ENDS_AT = 4  # день остаточно закривається о 04:00 наступного

RULES = """<b>Бали</b>
✓ звичка +10 · задача +15 · дедлайн +40
✓ із запізненням: задача +10 · дедлайн +20
✗ пропуск звички −5 (звички не переносяться)
↷ перенесення: задача −5 × №, дедлайн −10 × №
⏰ прострочено: задача −5, дедлайн −15 щодня
✕ скасування: задача −5, дедлайн −25
★ ідеальний день +30 · звіт +10 · екранний час +5
🔥 серія +2 за кожен день (до +20)"""

# Яйця: id, рідкість, підказка, метрика, поріг. Хто вилупиться — вирішує випадковий seed.
ROSTER = [
    ("first_step", "common", "Виконай першу справу", "tasks", 1),
    ("first_report", "common", "Надішли перший звіт", "reports", 1),
    ("first_voice", "common", "Надішли перший голосовий звіт", "voice", 1),
    ("streak_3", "common", "Серія 3 дні", "streak", 3),
    ("tasks_10", "common", "10 виконаних справ", "tasks", 10),
    ("level_3", "common", "Досягни 3 рівня", "level", 3),
    ("perfect_1", "rare", "Перший день на 100%", "perfect", 1),
    ("reports_7", "rare", "7 звітів", "reports", 7),
    ("streak_7", "rare", "Серія 7 днів", "streak", 7),
    ("tasks_50", "rare", "50 виконаних справ", "tasks", 50),
    ("screen_7", "rare", "7 днів фіксуй екранний час", "screen", 7),
    ("goal_half", "rare", "Будь-яка ціль на 50%", "goal_max", 50),
    ("voice_10", "rare", "10 голосових звітів", "voice", 10),
    ("level_5", "epic", "Досягни 5 рівня", "level", 5),
    ("perfect_5", "epic", "5 днів на 100%", "perfect", 5),
    ("streak_14", "epic", "Серія 14 днів", "streak", 14),
    ("goal_done", "epic", "Досягни будь-якої цілі", "goal_max", 100),
    ("tasks_100", "epic", "100 виконаних справ", "tasks", 100),
    ("month_70", "epic", "20 днів за місяць закрито на ≥70%", "closed_30", 20),
    ("level_10", "legendary", "Досягни 10 рівня", "level", 10),
    ("streak_30", "legendary", "Серія 30 днів", "streak", 30),
    ("all_goals", "legendary", "Всі цілі місяця на 100%", "goals_all", 1),
]


def init(state):
    state.setdefault("stats", {"xp": 0, "tasks": 0, "reports": 0, "voice": 0, "perfect": 0})
    for k, v in (("report_days", {}), ("unlocked", {}), ("goals", []), ("best_streak", 0),
                 ("screen", {}), ("ledger", []), ("done_pts", {}), ("charged", {})):
        state.setdefault(k, v)


def cutoff(now: datetime) -> date:
    """Останній день, який ще «триває»: до 04:00 це вчора."""
    return now.date() if now.hour >= DAY_ENDS_AT else now.date() - timedelta(days=1)


def points(state, day: date, pts: int, why: str):
    if not pts:
        return
    state["ledger"].append({"d": day.isoformat(), "p": pts, "w": why})
    state["stats"]["xp"] = max(0, state["stats"]["xp"] + pts)


def day_points(state, day: date) -> int:
    key = day.isoformat()
    return sum(x["p"] for x in state["ledger"] if x["d"] == key)


def potential(events) -> int:
    return sum(DONE[e["kind"]] for e in events)


# ---- рівні: на рівень n потрібно 50·n·(n−1) балів (0, 100, 300, 600, 1000…)

def level_floor(n):
    return 50 * n * (n - 1)


def level(xp):
    return int((1 + math.sqrt(1 + xp / 12.5)) / 2)


# ---- події

def on_done(state, ev, done: bool, now: datetime):
    today = now.date()
    t = ev["title"]
    if done:
        late = fmt.ev_day(ev) < cutoff(now)
        pts = (DONE_LATE if late else DONE)[ev["kind"]]
        state["done_pts"][ev["id"]] = pts
        points(state, today, pts, f"✓ {t}" + (" (із запізненням)" if late else ""))
    else:
        points(state, today, -state["done_pts"].pop(ev["id"], DONE[ev["kind"]]), f"↺ {t}")
    sign = 1 if done else -1
    state["stats"]["tasks"] = max(0, state["stats"]["tasks"] + sign)
    low = t.lower()
    for g in state["goals"]:
        if g.get("match") and any(m.strip() and m.strip().lower() in low for m in g["match"].split(",")):
            g["progress"] = max(0, g["progress"] + sign)


def on_move(state, ev, today: date) -> tuple:
    """Повертає (номер перенесення, штраф)."""
    n = ev.get("moves", 0) + 1
    pts = MOVE[ev["kind"]] * n
    points(state, today, pts, f"↷ {ev['title']} (перенесення №{n})")
    return n, pts


def on_cancel(state, ev, today: date) -> int:
    pts = CANCEL[ev["kind"]]
    points(state, today, pts, f"✕ {ev['title']}")
    return pts


def on_overdue(state, ev, today: date):
    key = f"{ev['id']}:{today.isoformat()}"
    if key in state["charged"]:
        return
    state["charged"][key] = today.isoformat()
    days = (today - fmt.ev_day(ev)).days
    points(state, today, OVERDUE[ev["kind"]], f"⏰ {ev['title']} (прострочено {days} дн)")


def on_report(state, today: date):
    key = today.isoformat()
    if key not in state["report_days"]:
        state["report_days"][key] = True
        state["stats"]["reports"] += 1
        points(state, today, REPORT, "звіт за день")


def on_screen(state, day: date, minutes: int, apps=None):
    first = day.isoformat() not in state["screen"]
    state["screen"][day.isoformat()] = {"min": int(minutes), "apps": (apps or [])[:5]}
    if first:
        points(state, day, SCREEN, "екранний час зафіксовано")


def on_voice(state):
    state["stats"]["voice"] += 1


# ---- дні

def update_days(state, events, now: datetime):
    """Оновлює статистику дня для вчора й сьогодні; закриває минулі дні з бонусами/штрафами."""
    today = now.date()
    for d in (today - timedelta(days=1), today):
        rec = state["days"].get(d.isoformat(), {})
        if rec.get("final"):
            continue
        evs = fmt.for_day(events, d)
        rec.update(
            planned=len(evs),
            done=sum(e["id"] in state["done"] for e in evs),
            missed=[e["title"] for e in evs if e["kind"] == "habit" and e["id"] not in state["done"]],
        )
        state["days"][d.isoformat()] = rec

    last_open = cutoff(now)
    for key in sorted(state["days"]):
        rec = state["days"][key]
        if key >= last_open.isoformat() or rec.get("final"):
            continue
        rec["final"] = True
        d = date.fromisoformat(key)
        for t in rec.get("missed", []):
            points(state, d, MISS_HABIT, f"✗ пропуск: {t}")
        if rec.get("planned") and rec["done"] >= rec["planned"]:
            state["stats"]["perfect"] += 1
            points(state, d, PERFECT, "★ ідеальний день")
        s = streak(state, d)
        if s:
            points(state, d, min(STREAK_MAX, STREAK_DAY * s), f"🔥 серія {s} дн")
        state["best_streak"] = max(state["best_streak"], s)


def pct(rec):
    if not rec or not rec.get("planned"):
        return None
    return round(100 * rec["done"] / rec["planned"])


def closed(rec):
    p = pct(rec)
    return p is not None and p >= CLOSED_PCT


def streak(state, until: date):
    """Скільки днів поспіль до until включно закрито. Дні без справ не рвуть серію."""
    n, d = 0, until
    for _ in range(400):
        rec = state["days"].get(d.isoformat())
        if rec is None:
            break
        if rec.get("planned"):
            if not closed(rec):
                break
            n += 1
        d -= timedelta(days=1)
    return n


def current_streak(state, today: date):
    s = streak(state, today - timedelta(days=1))
    return s + 1 if closed(state["days"].get(today.isoformat())) else s


# ---- цілі

def goal_pct(g):
    return min(100, round(100 * g["progress"] / g["target"])) if g["target"] else 0


# ---- яйця

def metrics(state, today):
    goals = [goal_pct(g) for g in state["goals"]]
    month = [state["days"].get((today - timedelta(days=i)).isoformat()) for i in range(30)]
    return {
        "tasks": state["stats"]["tasks"],
        "reports": state["stats"]["reports"],
        "voice": state["stats"]["voice"],
        "perfect": state["stats"]["perfect"],
        "streak": max(state["best_streak"], current_streak(state, today)),
        "level": level(state["stats"]["xp"]),
        "goal_max": max(goals, default=0),
        "goals_all": int(bool(goals) and min(goals) >= 100),
        "closed_30": sum(closed(r) for r in month),
        "screen": len(state["screen"]),
    }


def check_unlocks(state, today) -> list:
    m = metrics(state, today)
    new = []
    for aid, rarity, hint, metric, threshold in ROSTER:
        if aid not in state["unlocked"] and m[metric] >= threshold:
            state["unlocked"][aid] = {"d": today.isoformat(), "seed": random.randrange(1, 2**31)}
            new.append({"id": aid, "rarity": rarity})
    return new


def roster_view(state, today):
    m = metrics(state, today)
    out = []
    for aid, rarity, hint, metric, threshold in ROSTER:
        u = state["unlocked"].get(aid)
        out.append({"id": aid, "rarity": rarity, "hint": hint, "progress": min(1, m[metric] / threshold),
                    "unlocked": u["d"] if u else None, "seed": u["seed"] if u else None})
    return out

"""Гейміфікація: XP, рівні, серії, цілі, колекція динозаврів."""

import math
import random
from datetime import date, datetime, timedelta

from . import fmt

XP_TASK = 10
XP_REPORT = 25
XP_PERFECT = 50
XP_STREAK_DAY = 5  # × довжина серії, максимум 50
CLOSED_PCT = 70  # день «закрито», якщо виконано ≥ 70%

# Яйця: id, рідкість, підказка, метрика, поріг.
# Хто вилупиться — вирішує випадковий seed у момент відкриття.
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
    state.setdefault("report_days", {})
    state.setdefault("unlocked", {})
    state.setdefault("goals", [])
    state.setdefault("best_streak", 0)
    state.setdefault("screen", {})  # дата -> {min, apps}


def add_xp(state, n):
    state["stats"]["xp"] = max(0, state["stats"]["xp"] + n)


# ---- рівні: на рівень n потрібно 100·n·(n−1)/2 XP (0, 100, 300, 600, 1000…)

def level_floor(n):
    return 50 * n * (n - 1)


def level(xp):
    return int((1 + math.sqrt(1 + xp / 12.5)) / 2)


# ---- події

def on_done(state, title, done: bool):
    sign = 1 if done else -1
    state["stats"]["tasks"] = max(0, state["stats"]["tasks"] + sign)
    add_xp(state, sign * XP_TASK)
    t = title.lower()
    for g in state["goals"]:
        if g.get("match") and any(m.strip() and m.strip().lower() in t for m in g["match"].split(",")):
            g["progress"] = max(0, g["progress"] + sign)


def on_report(state, today: date):
    key = today.isoformat()
    if key not in state["report_days"]:
        state["report_days"][key] = True
        state["stats"]["reports"] += 1
        add_xp(state, XP_REPORT)


def on_screen(state, day: date, minutes: int, apps=None):
    first = day.isoformat() not in state["screen"]
    state["screen"][day.isoformat()] = {"min": int(minutes), "apps": (apps or [])[:5]}
    if first:
        add_xp(state, 5)


def on_voice(state):
    state["stats"]["voice"] += 1


# ---- дні

def update_days(state, events, now: datetime):
    """Оновлює planned/done для вчора й сьогодні; фіналізує минулі дні."""
    today = now.date()
    for d in (today - timedelta(days=1), today):
        rec = state["days"].get(d.isoformat(), {})
        if rec.get("final"):
            continue
        evs = fmt.for_day(events, d)
        rec.update(planned=len(evs), done=sum(e["id"] in state["done"] for e in evs))
        state["days"][d.isoformat()] = rec

    cutoff = today if now.hour >= 4 else today - timedelta(days=1)
    for key in sorted(state["days"]):
        rec = state["days"][key]
        if key < cutoff.isoformat() and not rec.get("final"):
            rec["final"] = True
            if rec["planned"] and rec["done"] >= rec["planned"]:
                state["stats"]["perfect"] += 1
                add_xp(state, XP_PERFECT)
            s = streak(state, date.fromisoformat(key))
            if s:
                add_xp(state, min(50, XP_STREAK_DAY * s))
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


# ---- досягнення

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
        "screen": len(state.get("screen", {})),
    }


def check_unlocks(state, today) -> list:
    """Повертає щойно відкриті досягнення."""
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

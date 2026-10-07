"""Облік витрат без бюджету: запис, підрахунок, звіти, попередження про незвично великі витрати."""

import uuid
from datetime import date, timedelta

CATEGORIES = [
    ("food", "🛒", "Їжа"),
    ("cafe", "🍔", "Кафе і фастфуд"),
    ("transport", "🚌", "Транспорт"),
    ("home", "🧴", "Побут і гігієна"),
    ("health", "💊", "Здоровʼя"),
    ("comm", "📶", "Звʼязок"),
    ("fun", "🎈", "Дозвілля"),
    ("housing", "🏠", "Житло"),
    ("other", "📦", "Інше"),
]
CAT = {k: (em, name) for k, em, name in CATEGORIES}
CAT_KEYS = [c[0] for c in CATEGORIES]

LOGGED_DAY = 5  # бали за день, коли витрати записані
CUR = "€"


def init(state):
    state.setdefault("expenses", [])
    state.setdefault("alerts", {})
    state.pop("budget", None)  # бюджет більше не використовується


def money(x, cur=CUR):
    s = f"{abs(x):,.2f}".replace(",", " ").replace(".", ",")
    return f"{'−' if x < 0 else ''}{s} {cur}"


def add_expense(state, amount, category, note="", day: date = None, source="text"):
    category = category if category in CAT_KEYS else "other"
    e = {"id": uuid.uuid4().hex[:8], "d": (day or date.today()).isoformat(), "amount": round(float(amount), 2),
         "cat": category, "note": note[:80], "src": source}
    state["expenses"].append(e)
    return e


def delete_expense(state, eid):
    before = len(state["expenses"])
    state["expenses"] = [e for e in state["expenses"] if e["id"] != eid]
    return len(state["expenses"]) < before


def week_start(d: date):
    return d - timedelta(days=d.weekday())


def _sum(items):
    return round(sum(e["amount"] for e in items), 2)


def period(state, first: date, last: date):
    items = [e for e in state["expenses"] if first.isoformat() <= e["d"] <= last.isoformat()]
    by_cat = {}
    for e in items:
        by_cat[e["cat"]] = round(by_cat.get(e["cat"], 0) + e["amount"], 2)
    days = (last - first).days + 1
    return {"total": _sum(items), "by_cat": dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
            "count": len(items), "days": days, "per_day": round(_sum(items) / days, 2) if days else 0}


def status(state, today: date):
    """Сьогодні / тиждень / місяць / середнє за день (за днями, коли щось записано)."""
    if not state["expenses"]:
        return None
    first_day = date.fromisoformat(min(e["d"] for e in state["expenses"]))
    tracked = max(1, (today - first_day).days + 1)
    last14 = period(state, max(first_day, today - timedelta(days=13)), today)
    return {
        "today": period(state, today, today),
        "week": period(state, week_start(today), today),
        "prev_week": period(state, week_start(today) - timedelta(days=7), week_start(today) - timedelta(days=1)),
        "month": period(state, today.replace(day=1), today),
        "all": period(state, first_day, today),
        "avg_day": round(_sum(state["expenses"]) / tracked, 2),
        "avg14": last14["per_day"],
        "tracked_days": tracked,
    }


def alerts(state, today: date):
    """Попередження, якщо сьогодні або категорія тижня помітно вища за звичне (не частіше раз на день)."""
    s = status(state, today)
    if not s or s["tracked_days"] < 5:
        return []
    out, t = [], today.isoformat()

    def once(key, text):
        k = f"{key}:{t}"
        if k not in state["alerts"]:
            state["alerts"][k] = t
            out.append(text)

    if s["today"]["total"] > max(s["avg14"] * 2, 10):
        once("day", f"⚠️ Сьогодні {money(s['today']['total'])} — це в {s['today']['total'] / max(s['avg14'], 0.01):.1f}× більше "
                    f"за звичний день ({money(s['avg14'])}).")
    prev = s["prev_week"]["by_cat"]
    for cat, amount in s["week"]["by_cat"].items():
        if prev.get(cat) and amount > prev[cat] * 1.5 and amount - prev[cat] > 10:
            em, name = CAT[cat]
            once(f"cat_{cat}", f"⚠️ {em} {name} цього тижня вже {money(amount)} — минулого тижня було {money(prev[cat])}.")
    return out


def close_day(state, d: date):
    if any(e["d"] == d.isoformat() for e in state["expenses"]):
        return [(LOGGED_DAY, "💶 витрати записано")]
    return []


# ---- тексти

def cats_line(by_cat, limit=4):
    return " · ".join(f"{CAT[k][0]} {money(v)}" for k, v in list(by_cat.items())[:limit])


def short_line(state, today):
    s = status(state, today)
    if not s:
        return "💶 Витрати: надсилай голосом, текстом або фото чека."
    y = period(state, today - timedelta(days=1), today - timedelta(days=1))
    return f"💶 Вчора {money(y['total'])} · тиждень {money(s['week']['total'])} · у середньому {money(s['avg_day'])}/день"


def day_report(state, today):
    s = status(state, today)
    if not s:
        return "💶 Витрат сьогодні не записано. Що купував? Голосом, текстом або фото чека."
    t = s["today"]
    head = f"💶 Сьогодні {money(t['total'])}" + (f" · {cats_line(t['by_cat'], 3)}" if t["count"] else "")
    return f"{head}\nТиждень {money(s['week']['total'])}. Що ще купував? Голосом, текстом або фото чека."


def week_report(state, today):
    s = status(state, today)
    if not s:
        return ""
    w, p = s["week"], s["prev_week"]
    diff = ""
    if p["total"]:
        delta = w["total"] - p["total"]
        diff = f" · {'↑' if delta > 0 else '↓'} {money(abs(delta))} до минулого тижня"
    top = max(w["by_cat"].items(), key=lambda kv: kv[1]) if w["by_cat"] else None
    lines = [f"<b>💶 Тиждень: {money(w['total'])}</b>{diff}", cats_line(w["by_cat"], 6)]
    if top and w["total"]:
        lines.append(f"Найбільше — {CAT[top[0]][1].lower()} ({round(100 * top[1] / w['total'])}%).")
    return "\n".join(x for x in lines if x)


# ---- раціон (окремий агент, за запитом)

MEAL_PROMPT = """Ти — дієтолог-економіст. Склади раціон на 7 днів для однієї дорослої людини в Латвії (Lidl, Maxima, Rimi).
Сума на продукти: {budget} на тиждень — не перевищуй. Ціни — реалістичні латвійські.
Прості дешеві продукти, 3 прийоми їжі + перекус, ~2000–2300 ккал і ≥100 г білка на день, готування на 2 дні, мінімум відходів.
Формат — простий текст українською, стисло: 🛒 список покупок (продукт — кількість — ціна, «Разом: N €»), 🍽 меню Пн–Нд по рядку, 💡 3 поради."""


def make_meal_plan(client, model, state, weekly_amount: float):
    text = client.chat.completions.create(
        model=model, temperature=0.4,
        messages=[{"role": "user", "content": MEAL_PROMPT.format(budget=money(weekly_amount))}],
    ).choices[0].message.content.strip()
    state["meal_plan"] = {"budget": weekly_amount, "text": text}
    return text

"""Бюджет і витрати: план, ліміт на сьогодні, тижневий ліміт на їжу, контроль темпу, раціон."""

import uuid
from datetime import date, timedelta

from . import config

BUFFER_PCT = 10  # подушка безпеки — не витрачається без потреби
# Частки гнучкого бюджету (після обовʼязкових платежів і подушки)
CATEGORIES = [
    ("food", "🛒", "Їжа", 55),
    ("transport", "🚌", "Транспорт", 10),
    ("home", "🧴", "Побут і гігієна", 10),
    ("health", "💊", "Здоровʼя", 5),
    ("comm", "📶", "Звʼязок", 5),
    ("fun", "🎈", "Дозвілля", 5),
    ("other", "📦", "Інше", 10),
]
CAT = {k: (em, name, share) for k, em, name, share in CATEGORIES}
CAT_KEYS = [c[0] for c in CATEGORIES] + ["fixed"]

WITHIN_DAY = 10  # бали за день у межах ліміту
OVER_DAY = -10  # бали за перевитрату дня
LOGGED_DAY = 5  # бали за записані витрати


def init(state):
    state.setdefault("budget", None)
    state.setdefault("expenses", [])
    state.setdefault("meal_plan", None)
    state.setdefault("alerts", {})


def money(x, cur="€"):
    s = f"{x:,.2f}".replace(",", " ").replace(".", ",")
    return f"{s} {cur}"


def set_budget(state, total, start: date, end: date, fixed=None, currency="€"):
    state["budget"] = {
        "total": round(float(total), 2), "currency": currency,
        "start": start.isoformat(), "end": end.isoformat(),
        "fixed": [{"name": f["name"], "amount": round(float(f["amount"]), 2)} for f in (fixed or [])],
    }
    return plan(state)


def plan(state):
    b = state.get("budget")
    if not b:
        return None
    fixed = sum(f["amount"] for f in b["fixed"])
    free = max(0.0, b["total"] - fixed)
    buffer = round(free * BUFFER_PCT / 100, 2)
    flexible = round(free - buffer, 2)
    days = (date.fromisoformat(b["end"]) - date.fromisoformat(b["start"])).days + 1
    limits = {k: round(flexible * share / 100, 2) for k, (_, _, share) in CAT.items()}
    return {"fixed": round(fixed, 2), "buffer": buffer, "flexible": flexible, "days": days,
            "limits": limits, "food_week": round(limits["food"] * 7 / days, 2),
            "per_day": round(flexible / days, 2)}


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


def _in_period(state, e):
    b = state.get("budget")
    return bool(b) and b["start"] <= e["d"] <= b["end"]


def week_start(d: date):
    return d - timedelta(days=d.weekday())


def status(state, today: date):
    """Головні числа: ліміт на сьогодні, залишок, тиждень їжі, категорії."""
    b, p = state.get("budget"), plan(state)
    if not p:
        return None
    exp = [e for e in state["expenses"] if _in_period(state, e)]
    flex = [e for e in exp if e["cat"] != "fixed"]
    t = today.isoformat()
    start, end = date.fromisoformat(b["start"]), date.fromisoformat(b["end"])
    day = min(max(today, start), end)
    days_left = (end - day).days + 1
    spent_before = sum(e["amount"] for e in flex if e["d"] < t)
    spent_today = sum(e["amount"] for e in flex if e["d"] == t)
    allow_today = round(max(0.0, p["flexible"] - spent_before) / days_left, 2)
    ws = week_start(today).isoformat()
    food_week = sum(e["amount"] for e in flex if e["cat"] == "food" and e["d"] >= ws and e["d"] <= t)
    by_cat = {k: round(sum(e["amount"] for e in exp if e["cat"] == k), 2) for k in CAT_KEYS}
    elapsed = ((day - start).days + 1) / p["days"]
    return {
        "currency": b["currency"], "total": b["total"], **p,
        "spent": round(sum(e["amount"] for e in flex), 2),
        "spent_today": round(spent_today, 2), "allow_today": allow_today,
        "left_today": round(allow_today - spent_today, 2),
        "left_month": round(p["flexible"] - spent_before - spent_today, 2),
        "days_left": days_left, "elapsed": round(elapsed, 3),
        "food_week_spent": round(food_week, 2), "by_cat": by_cat,
        "fixed_paid": by_cat["fixed"],
    }


def alerts(state, today: date):
    """Нові попередження (кожне — не частіше раз на день)."""
    s = status(state, today)
    if not s:
        return []
    cur, out, t = s["currency"], [], today.isoformat()

    def once(key, text):
        k = f"{key}:{t}"
        if k not in state["alerts"]:
            state["alerts"][k] = t
            out.append(text)

    if s["spent_today"] > s["allow_today"] * 1.0 and s["spent_today"] > 0:
        once("day", f"⚠️ Ліміт дня перевищено: {money(s['spent_today'], cur)} з {money(s['allow_today'], cur)}. "
                    f"Завтра ліміт стане меншим.")
    if s["food_week_spent"] >= s["food_week"] * 0.8:
        left = s["food_week"] - s["food_week_spent"]
        once("food", f"⚠️ Їжа цього тижня: {money(s['food_week_spent'], cur)} з {money(s['food_week'], cur)}"
                     + (f" — лишилось {money(left, cur)}." if left > 0 else " — тижневий ліміт вичерпано."))
    for k, (em, name, _) in CAT.items():
        lim, spent = s["limits"][k], s["by_cat"][k]
        if k != "food" and lim and spent > lim * max(s["elapsed"], 0.25) * 1.2 and spent > lim * 0.5:
            once(f"cat_{k}", f"⚠️ {em} {name}: {money(spent, cur)} з {money(lim, cur)} на місяць — темп завеликий.")
    if s["left_month"] < 0:
        once("month", f"🚨 Гнучкий бюджет вичерпано на {money(-s['left_month'], cur)}. Далі — лише з подушки ({money(s['buffer'], cur)}).")
    return out


def close_day(state, d: date):
    """Підсумок дня для балів: (бали, причина) або None."""
    s = status(state, d)
    if not s or not (state.get("budget", {})["start"] <= d.isoformat() <= state["budget"]["end"]):
        return []
    res = []
    if any(e["d"] == d.isoformat() for e in state["expenses"]):
        res.append((LOGGED_DAY, "💶 витрати записано"))
    if s["spent_today"] <= s["allow_today"]:
        res.append((WITHIN_DAY, "💶 день у межах бюджету"))
    else:
        res.append((OVER_DAY, f"💶 перевитрата {money(s['spent_today'] - s['allow_today'], s['currency'])}"))
    return res


# ---- текст для повідомлень

def short_line(state, today):
    s = status(state, today)
    if not s:
        return "💶 Бюджет не задано — скажи боту суму на місяць."
    cur = s["currency"]
    return (f"💶 Можна сьогодні: <b>{money(max(0, s['left_today']), cur)}</b> · залишок {money(s['left_month'], cur)}"
            f" · їжа тиждень {money(s['food_week_spent'], cur)}/{money(s['food_week'], cur)}")


def plan_text(state, today):
    s = status(state, today)
    cur = s["currency"]
    lines = [f"<b>Бюджет {money(s['total'], cur)}</b> · {s['days']} днів",
             f"Обовʼязкові: {money(s['fixed'], cur)}" if s["fixed"] else None,
             f"Подушка {BUFFER_PCT}%: {money(s['buffer'], cur)} — не чіпаємо",
             f"На життя: {money(s['flexible'], cur)} ≈ {money(s['per_day'], cur)}/день",
             f"🛒 Їжа: {money(s['food_week'], cur)} на тиждень"]
    lines += [f"{em} {name}: {money(s['limits'][k], cur)}" for k, (em, name, _) in CAT.items() if k != "food"]
    return "\n".join(x for x in lines if x)


# ---- раціон (окремий агент)

MEAL_PROMPT = """Ти — дієтолог-економіст. Склади раціон на 7 днів для однієї дорослої людини в Латвії (магазини Lidl, Maxima, Rimi).
Бюджет на їжу: {budget} на тиждень — не перевищуй, залиш 5% запасу. Ціни — реалістичні латвійські.
Принципи: прості дешеві продукти (крупи, яйця, курка, бобові, сезонні овочі, кефір/сир), 3 прийоми їжі + перекус,
~2000–2300 ккал і ≥100 г білка на день, готування великими порціями на 2 дні, мінімум відходів. Людина записує їжу в FatSecret.

Формат — простий текст українською, без markdown-таблиць, стисло:
🛒 Список покупок (продукт — кількість — ціна), внизу «Разом: N €».
🍽 Меню: Пн–Нд, по рядку на день (сніданок / обід / вечеря / перекус).
💡 3 короткі поради економії."""


def make_meal_plan(client, model, state, today):
    s = status(state, today)
    if not s:
        return None
    text = client.chat.completions.create(
        model=model, temperature=0.4,
        messages=[{"role": "user", "content": MEAL_PROMPT.format(budget=money(s["food_week"], s["currency"]))}],
    ).choices[0].message.content.strip()
    state["meal_plan"] = {"week": week_start(today).isoformat(), "budget": s["food_week"], "text": text}
    return text

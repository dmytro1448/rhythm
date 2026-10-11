"""Одноразові виправлення даних. Виконуються ботом у циклі (без гонок зі станом на GitHub)."""

from datetime import date, timedelta

from . import finance, fmt, game, gcal


def fix_2026_10_11(state, now):
    """Помилки агента 8–10 жовтня: підйом/відбій не прибрались, хибні штрафи, втрачена витрата."""
    today = now.date()
    # 1. Підйом і відбій — прибрати з усіх днів (вся серія) і їхні цілі
    for e in gcal.list_events(today, today + timedelta(days=2)):
        if e["kind"] == "habit" and any(w in e["title"].lower() for w in ("підйом", "відбій")):
            try:
                gcal.delete_event(e["id"], series=True)
            except Exception:
                pass  # серію вже прибрано через інший екземпляр
    state["goals"] = [g for g in state["goals"] if g.get("match") not in ("Підйом", "Відбій")]
    # 2. Зайва задача, яку агент двічі «видаляв»
    for e in gcal.list_deadlines(today - timedelta(days=7)):
        if "дізнатись, чи можна ще взяти sim" in e["title"].lower():
            gcal.delete_event(e["id"])
    # 3. Повернення хибних штрафів
    for d, pts, why in [
        ("2026-10-08", 10, "підйом/відбій видалено помилково"),
        ("2026-10-09", 25, "тренування видалено замість перенесення"),
        ("2026-10-09", 20, "підйом/відбій: хибні штрафи"),
        ("2026-10-09", 5, "зайве перенесення задачі"),
    ]:
        game.points(state, date.fromisoformat(d), pts, f"↺ виправлення помилки агента: {why}")
    # 4. Витрата, яку агент «записав», але не зберіг
    finance.add_expense(state, 25, "other", "шишки", date(2026, 10, 10))


MIGRATIONS = [("2026-10-11-fix", fix_2026_10_11)]


def run(state, now):
    done = state.setdefault("migrations", [])
    for key, fn in MIGRATIONS:
        if key not in done:
            fn(state, now)
            done.append(key)
            print("migration applied:", key)

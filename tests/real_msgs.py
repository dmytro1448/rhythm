"""Справжні повідомлення, на яких агент помилявся 8–10 жовтня (живий виклик OpenAI, ~1 цент)."""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mockcal as M  # noqa: E402
from bot import agent, config, fmt, game, store  # noqa: E402

D = date(2026, 10, 8)
for i in range(6):
    for h in ("Підйом до 9:00", "Відбій до 00:00", "Розтяжка", "Python-курс · 1 год"):
        M.add(h, D + timedelta(days=i), "habit")
M.add("Тренування", D + timedelta(days=1), "deadline")
M.add("Дізнатись, чи можна ще взяти SIM-карту", D + timedelta(days=1), "task")
st = store._default()
game.init(st)
now = datetime(2026, 10, 8, 22, 10, tzinfo=config.TZ)
for t in ["Я зробив розтяжку. Познач як виконане. Завдання стосовно підйому та відбою прибери взагалі. Не треба рахувати за нього бали. "
          "На завтра замість розтяжки додай завдання качати прес. Також обовʼязковим завданням з дедлайном на завтра постав завдання сходити та зробити сім-карту.",
          "Зробити сім-карту та зробити тренування — обидві задачі перенеси дедлайн на понеділок.",
          "Видали задачу дізнатися, чи можна ще взяти SIM-карту. Я вже дізнався.",
          "За вчора 25 євро потратив на шишки."]:
    r, used = agent.run(st, t, now)
    print(f"> {t[:90]}\n< " + r.replace("\n", "\n  "))
print("  ЛИШИЛОСЬ:", sorted({e["title"] for e in M.DB.values()}))
print("  не звички:", [(fmt.ev_day(e).isoformat(), e["kind"], e["title"]) for e in M.DB.values() if e["kind"] != "habit"])
print("  витрати:", [(e["d"], e["amount"], e["note"]) for e in st["expenses"]])
print("  бали:", [(x["p"], x["w"]) for x in st["ledger"]])

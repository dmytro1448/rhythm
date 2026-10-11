"""Механіка балів і розкладу без OpenAI: python tests/scenario.py"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mockcal as M  # noqa: E402
from bot import agent, config, game, main, scheduler, store  # noqa: E402
from bot import telegram as tg  # noqa: E402

config.CHAT_ID, config.APP_KEY = 1, ""
OUT = []
tg.send = lambda text, buttons=None, html=False, chat_id=None: OUT.append(text)
tg.call = lambda m, p=None, http_timeout=30: {}
D0 = date(2026, 10, 7)
for d in range(3):
    for h in ("Розтяжка", "Python-курс · 1 год", "Їжа у FatSecret"):
        M.add(h, D0 + timedelta(days=d), "habit")
T1 = M.add("Дізнатись про SIM", D0, "task")
DL = M.add("Документи", D0 + timedelta(days=1), "deadline")
st = store._default()
game.init(st)


def at(d, h, m=0):
    return datetime.combine(D0 + timedelta(days=d), datetime.min.time(), config.TZ).replace(hour=h, minute=m)


scheduler.run_jobs(st, at(0, 9, 5))
assert any("Середа, 7 жовтня" in o for o in OUT), "ранкове повідомлення"
habits = [e["id"] for e in M.list_events(D0, D0) if e["kind"] == "habit"]
assert agent.set_done(st, habits[:2], True, at(0, 12)) == 20
_, pts = agent.move_event(st, T1, D0 + timedelta(days=1), at(0, 21))
assert pts == -5
try:
    agent.move_event(st, habits[2], D0 + timedelta(days=1), at(0, 21))
    raise AssertionError("звичку не можна переносити")
except agent.Refused:
    pass
scheduler.run_jobs(st, at(1, 4, 10))  # закриття дня 1: пропуск 1 звички
day1 = [x["p"] for x in st["ledger"] if x["d"] == D0.isoformat()]
assert sorted(day1) == [-5, -5, 10, 10], day1
_, pts = agent.move_event(st, T1, D0 + timedelta(days=2), at(1, 21))
assert pts == -10, "друге перенесення −10"
before = st["stats"]["xp"]
scheduler.run_jobs(st, at(3, 9, 1))
scheduler.run_jobs(st, at(3, 9, 30))
charged = [x for x in st["ledger"] if x["w"].startswith("⏰")]
assert len({x["w"] for x in charged}) == len(charged), "прострочення — раз на добу"
print("scenario OK · балів:", st["stats"]["xp"])

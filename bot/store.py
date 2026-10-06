"""Стан бота: offset Telegram, історія діалогу, виконані справи, нотатки, статистика.

На GitHub стан зберігається зашифрованим у data/state.enc і комітиться назад у репозиторій.
"""

import json
from datetime import datetime, timedelta

from cryptography.fernet import Fernet

from . import config, game

ENC_PATH = config.ROOT / "data" / "state.enc"
PLAIN_PATH = config.ROOT / "data" / "state.json"

_loaded = ""


def _default():
    return {
        "offset": 0,
        "history": [],  # останні репліки діалогу з агентом
        "sent": {},  # "morning:2026-10-07" -> дата
        "reminded": {},  # event_id -> дата
        "done": {},  # event_id -> дата позначки
        "btn": {},  # короткий ключ кнопки -> {id, t, d}
        "log": [],  # нотатки зі звітів
        "days": {},  # дата -> {planned, done}
    }


def load():
    global _loaded
    raw = ""
    if config.STATE_KEY:
        if ENC_PATH.exists():
            raw = Fernet(config.STATE_KEY.encode()).decrypt(ENC_PATH.read_bytes()).decode()
    elif PLAIN_PATH.exists():
        raw = PLAIN_PATH.read_text()
    state = _default()
    if raw:
        state.update(json.loads(raw))
    _loaded = raw
    game.init(state)
    return state


def save(state) -> bool:
    _prune(state)
    raw = json.dumps(state, ensure_ascii=False, sort_keys=True)
    if raw == _loaded:
        return False
    ENC_PATH.parent.mkdir(exist_ok=True)
    if config.STATE_KEY:
        ENC_PATH.write_bytes(Fernet(config.STATE_KEY.encode()).encrypt(raw.encode()))
    else:
        PLAIN_PATH.write_text(raw)
    return True


def _prune(s):
    today = datetime.now(config.TZ).date()
    short = (today - timedelta(days=3)).isoformat()
    long = (today - timedelta(days=90)).isoformat()
    s["sent"] = {k: v for k, v in s["sent"].items() if v >= short}
    s["reminded"] = {k: v for k, v in s["reminded"].items() if v >= short}
    s["btn"] = {k: v for k, v in s["btn"].items() if v["d"] >= short}
    s["done"] = {k: v for k, v in s["done"].items() if v >= long}
    s["days"] = {k: v for k, v in s["days"].items() if k >= long}
    s["history"] = s["history"][-20:]
    s["log"] = s["log"][-300:]
    s["screen"] = {k: v for k, v in s["screen"].items() if k >= long}
    s["report_days"] = {k: v for k, v in s["report_days"].items() if k >= long}

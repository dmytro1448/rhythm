"""Знімок прогресу для міні-застосунку. Шифрується AES-GCM ключем APP_KEY,
який живе лише в посиланні на застосунок (не в репозиторії)."""

import base64
import hashlib
import json
import os
from datetime import datetime, timedelta

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import config, fmt, game

PATH = config.ROOT / "data" / "progress.enc"


def _key():
    k = config.APP_KEY
    return base64.urlsafe_b64decode(k + "=" * (-len(k) % 4))


def snapshot(state, events, now: datetime):
    today = now.date()
    xp = state["stats"]["xp"]
    lvl = game.level(xp)
    tasks = fmt.for_day(events, today)

    heat = []
    for i in range(41, -1, -1):
        d = today - timedelta(days=i)
        rec = state["days"].get(d.isoformat())
        notes = [x for x in state["log"] if x["date"] == d.isoformat()]
        energy = [x["energy"] for x in notes if x.get("energy")]
        heat.append({
            "d": d.isoformat(), "pct": game.pct(rec),
            "planned": rec["planned"] if rec else 0, "done": rec["done"] if rec else 0,
            "energy": round(sum(energy) / len(energy), 1) if energy else None,
            "notes": [x["text"] for x in notes][-3:],
            "report": d.isoformat() in state["report_days"],
            "screen": state["screen"].get(d.isoformat(), {}).get("min"),
        })

    return {
        "v": 1,
        "today": {
            "date": today.isoformat(), "title": fmt.day_title(today),
            "tasks": [{"id": e["id"], "title": e["title"], "time": "" if e["all_day"] else fmt.when(e),
                       "done": e["id"] in state["done"]} for e in tasks],
        },
        "tomorrow": [{"title": e["title"], "time": "" if e["all_day"] else fmt.when(e)}
                     for e in fmt.for_day(events, today + timedelta(days=1))],
        "player": {
            "xp": xp, "level": lvl, "floor": game.level_floor(lvl), "next": game.level_floor(lvl + 1),
            "streak": game.current_streak(state, today), "best": state["best_streak"],
            **{k: state["stats"][k] for k in ("tasks", "reports", "voice", "perfect")},
        },
        "goals": [{**g, "pct": game.goal_pct(g)} for g in state["goals"]],
        "heat": heat,
        "roster": game.roster_view(state, today),
    }


def publish(state, events, now) -> bool:
    if not config.APP_KEY:
        return False
    data = json.dumps(snapshot(state, events, now), ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(data.encode()).hexdigest()
    if state.get("progress_hash") == digest and PATH.exists():
        return False
    nonce = os.urandom(12)
    blob = nonce + AESGCM(_key()).encrypt(nonce, data.encode(), None)
    PATH.write_text(base64.b64encode(blob).decode())
    state["progress_hash"] = digest
    return True


def app_url():
    if not config.WEBAPP_URL:
        return ""
    return f"{config.WEBAPP_URL}?r={config.GITHUB_REPO}&k={config.APP_KEY}"

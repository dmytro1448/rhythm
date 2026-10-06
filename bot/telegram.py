import requests

from . import config

LIMIT = 4000


def call(method, params=None, http_timeout=30):
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/{method}"
    data = requests.post(url, json=params or {}, timeout=http_timeout).json()
    if not data.get("ok"):
        raise RuntimeError(f"telegram {method}: {data.get('description')}")
    return data["result"]


def get_updates(offset, poll=0):
    params = {"offset": offset, "timeout": poll, "allowed_updates": ["message", "callback_query"]}
    return call("getUpdates", params, http_timeout=poll + 15)


def send(text, buttons=None, html=False, chat_id=None):
    """buttons: список рядків [(текст, callback_data), ...]"""
    chunks = _split(text)
    for i, chunk in enumerate(chunks):
        params = {"chat_id": chat_id or config.CHAT_ID, "text": chunk, "disable_web_page_preview": True}
        if html:
            params["parse_mode"] = "HTML"
        if buttons and i == len(chunks) - 1:
            params["reply_markup"] = keyboard(buttons)
        call("sendMessage", params)


def keyboard(buttons):
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in buttons]}


def typing():
    try:
        call("sendChatAction", {"chat_id": config.CHAT_ID, "action": "typing"})
    except Exception:
        pass


def download(file_id) -> bytes:
    path = call("getFile", {"file_id": file_id})["file_path"]
    url = f"https://api.telegram.org/file/bot{config.TELEGRAM_TOKEN}/{path}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.content


def _split(text):
    if len(text) <= LIMIT:
        return [text]
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > LIMIT:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    return chunks + [cur] if cur.strip() else chunks

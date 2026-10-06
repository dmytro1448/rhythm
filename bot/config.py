import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def _int(name, default):
    return int(os.getenv(name) or default)


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = _int("TELEGRAM_CHAT_ID", 0)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
TRANSCRIBE_MODEL = os.getenv("TRANSCRIBE_MODEL") or "gpt-4o-mini-transcribe"
TRANSCRIBE_LANGUAGE = os.getenv("TRANSCRIBE_LANGUAGE") or "uk"

# JSON-вміст ключа сервісного акаунта або шлях до файлу з ним
GOOGLE_SA_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID") or "primary"

# Ключ шифрування стану (Fernet). Без нього стан пишеться відкритим у data/state.json
STATE_KEY = os.getenv("STATE_KEY", "")

TZ = ZoneInfo(os.getenv("TIMEZONE") or "Europe/Kyiv")
MORNING_HOUR = _int("MORNING_HOUR", 8)
EVENING_HOUR = _int("EVENING_HOUR", 20)
REMIND_BEFORE_MIN = _int("REMIND_BEFORE_MIN", 60)

DEBUG = bool(os.getenv("DEBUG"))

# Міні-застосунок прогресу (GitHub Pages) і репозиторій, звідки він читає дані
APP_KEY = os.getenv("APP_KEY", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")

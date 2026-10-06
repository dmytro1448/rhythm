"""Google Calendar — джерело правди про справи."""

import json
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build

from . import config

DONE_COLOR = "8"  # графітовий — виконані справи


@lru_cache
def _svc():
    raw = config.GOOGLE_SA_JSON.strip()
    info = json.loads(raw if raw.startswith("{") else Path(raw).read_text())
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/calendar"]
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _events():
    return _svc().events()


def _parse(ev):
    s, e = ev["start"], ev["end"]
    all_day = "date" in s
    if all_day:
        start, end = date.fromisoformat(s["date"]), date.fromisoformat(e["date"])
    else:
        start = datetime.fromisoformat(s["dateTime"]).astimezone(config.TZ)
        end = datetime.fromisoformat(e["dateTime"]).astimezone(config.TZ)
    remind = ev.get("extendedProperties", {}).get("private", {}).get("remind", "")
    return {
        "id": ev["id"],
        "title": ev.get("summary") or "(без назви)",
        "start": start,
        "end": end,
        "all_day": all_day,
        "description": ev.get("description", ""),
        "remind": int(remind) if remind.isdigit() else None,
    }


def list_events(first: date, last: date, query=None):
    """Події з first по last включно, повторювані розгорнуті в окремі екземпляри."""
    params = {
        "calendarId": config.CALENDAR_ID,
        "timeMin": datetime.combine(first, time.min, config.TZ).isoformat(),
        "timeMax": datetime.combine(last + timedelta(days=1), time.min, config.TZ).isoformat(),
        "singleEvents": True,
        "orderBy": "startTime",
        "maxResults": 250,
    }
    if query:
        params.update(query)
        params = {k: v for k, v in params.items() if v is not None}
    items, token = [], None
    while True:
        res = _events().list(pageToken=token, **params).execute()
        items += res.get("items", [])
        token = res.get("nextPageToken")
        if not token:
            break
    return [_parse(e) for e in items if e.get("status") != "cancelled"]


def get_event(event_id):
    return _parse(_events().get(calendarId=config.CALENDAR_ID, eventId=event_id).execute())


def _hm(s):
    return time.fromisoformat(s)


def _times(day: date, start_time=None, end_time=None, duration_min=None):
    if not start_time:
        return {"date": day.isoformat()}, {"date": (day + timedelta(days=1)).isoformat()}
    start = datetime.combine(day, _hm(start_time), config.TZ)
    if end_time:
        end = datetime.combine(day, _hm(end_time), config.TZ)
        if end <= start:
            end += timedelta(days=1)
    else:
        end = start + timedelta(minutes=duration_min or 60)
    tz = config.TZ.key
    return {"dateTime": start.isoformat(), "timeZone": tz}, {"dateTime": end.isoformat(), "timeZone": tz}


def rrule_until(last: date):
    end = datetime.combine(last, time(23, 59, 59), config.TZ).astimezone(timezone.utc)
    return end.strftime("%Y%m%dT%H%M%SZ")


def create_event(title, day: date, start_time=None, end_time=None, duration_min=None,
                 description="", recurrence=None, remind_before_min=None, source=None):
    start, end = _times(day, start_time, end_time, duration_min)
    body = {"summary": title, "start": start, "end": end}
    if description:
        body["description"] = description
    if recurrence:
        body["recurrence"] = [r if r.startswith("RRULE:") else f"RRULE:{r}" for r in recurrence]
    props = {}
    if remind_before_min is not None:
        props["remind"] = str(int(remind_before_min))
    if source:
        props["source"] = source
    if props:
        body["extendedProperties"] = {"private": props}
    ev = _events().insert(calendarId=config.CALENDAR_ID, body=body).execute()
    return _parse(ev)


def update_event(event_id, title=None, day=None, start_time=None, end_time=None,
                 description=None, remind_before_min=None):
    body = {}
    if title is not None:
        body["summary"] = title
    if description is not None:
        body["description"] = description
    if remind_before_min is not None:
        body["extendedProperties"] = {"private": {"remind": str(int(remind_before_min))}}
    if day or start_time or end_time:
        cur = get_event(event_id)
        if cur["all_day"]:
            new_day = day or cur["start"]
            if start_time:
                body["start"], body["end"] = _times(new_day, start_time, end_time)
            else:
                span = cur["end"] - cur["start"]
                body["start"] = {"date": new_day.isoformat()}
                body["end"] = {"date": (new_day + span).isoformat()}
        else:
            new_day = day or cur["start"].date()
            st = start_time or cur["start"].strftime("%H:%M")
            dur = int((cur["end"] - cur["start"]).total_seconds() // 60)
            body["start"], body["end"] = _times(new_day, st, end_time, dur)
    ev = _events().patch(calendarId=config.CALENDAR_ID, eventId=event_id, body=body).execute()
    return _parse(ev)


def delete_event(event_id, series=False):
    """series=True — видалити всю повторювану серію, до якої належить подія."""
    if series:
        raw = _events().get(calendarId=config.CALENDAR_ID, eventId=event_id).execute()
        event_id = raw.get("recurringEventId", event_id)
    _events().delete(calendarId=config.CALENDAR_ID, eventId=event_id).execute()


def set_done(event_id, done: bool):
    """Візуально позначає виконану справу в календарі (сірий колір)."""
    try:
        ev = _events().patch(
            calendarId=config.CALENDAR_ID, eventId=event_id,
            body={"colorId": DONE_COLOR if done else None},
        ).execute()
        return ev.get("summary", "")
    except Exception as e:
        print("set_done failed:", type(e).__name__)
        return ""

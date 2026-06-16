"""
Tracks how many Gemini API requests Scout has made today, so it can warn the
user before the free daily quota runs out and announce when it is gone.

Google's free tier is a *daily request limit* (not a dollar balance), and there
is no API to read the remaining count -- so we count locally in usage.json and
compare against config.FREE_TIER_DAILY_LIMIT for the early heads-up. The
authoritative "you're out" signal is a 429 from the API (handled in main.py),
which calls mark_exhausted() here so Scout stops hammering the API for the rest
of the day. Everything resets automatically when the date rolls over.
"""

import json
from datetime import date

import config


def _fresh(today):
    return {"date": today, "count": 0, "warned": False, "exhausted": False}


def _load():
    today = date.today().isoformat()
    try:
        with open(config.USAGE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    # Roll everything over at the start of a new day.
    if data.get("date") != today:
        data = _fresh(today)
    return data


def _save(data):
    try:
        with open(config.USAGE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass  # tracking is best-effort; never let it break a turn


def record():
    """Count one successful API request against today's quota."""
    data = _load()
    data["count"] = data.get("count", 0) + 1
    _save(data)
    return data["count"]


def fraction_used():
    """How much of the configured daily free limit we've used (0.0 - 1.0)."""
    data = _load()
    limit = max(1, config.FREE_TIER_DAILY_LIMIT)
    return min(1.0, data.get("count", 0) / limit)


def should_announce_warning():
    """True exactly once per day, the first time we cross the warn threshold."""
    data = _load()
    if data.get("warned"):
        return False
    if fraction_used() >= config.FREE_WARN_FRACTION:
        data["warned"] = True
        _save(data)
        return True
    return False


def mark_exhausted():
    """Record that the API itself reported the daily free quota is gone."""
    data = _load()
    data["exhausted"] = True
    data["count"] = max(data.get("count", 0), config.FREE_TIER_DAILY_LIMIT)
    _save(data)


def is_exhausted():
    """True only if a real 429 happened today (authoritative, resets daily)."""
    return _load().get("exhausted", False)

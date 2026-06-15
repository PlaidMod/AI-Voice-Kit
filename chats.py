"""
Conversation memory.

Every conversation is stored as one JSON file in the `conversations/` folder so
Scout remembers things across reboots. The user can ask Scout to list recent
chats and continue any of them (the model calls the tools in assistant.py, which
call the functions here).

We deliberately store conversations as simple {"role", "content": "<text>"}
turns -- just what was said and what was answered. We do NOT store the model's
internal web-search results. That keeps the files small, easy to read, and
safe to replay on a later turn.
"""

import json
import os
import time
from datetime import datetime

from config import CONVERSATIONS_DIR


class Conversation:
    def __init__(self, id, title="", messages=None, updated=None):
        self.id = id
        self.title = title
        self.messages = messages or []          # list of {"role", "content": str}
        self.updated = updated or time.time()

    def add_turn(self, user_text, assistant_text):
        """Record one question and its answer."""
        self.messages.append({"role": "user", "content": user_text})
        self.messages.append({"role": "assistant", "content": assistant_text})
        if not self.title:
            self.title = _make_title(user_text)
        self.updated = time.time()

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "messages": self.messages,
            "updated": self.updated,
        }


def _make_title(text):
    """A short, human-friendly title taken from the first question."""
    words = text.strip().split()
    title = " ".join(words[:6])
    return title + ("..." if len(words) > 6 else "")


def _path(conv_id):
    return os.path.join(CONVERSATIONS_DIR, f"{conv_id}.json")


def new_conversation():
    """Start a fresh, empty conversation with a unique id."""
    os.makedirs(CONVERSATIONS_DIR, exist_ok=True)
    conv_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Conversation(id=conv_id)


def save(conv):
    """Write a conversation to disk (only if it actually has content)."""
    if not conv.messages:
        return
    os.makedirs(CONVERSATIONS_DIR, exist_ok=True)
    with open(_path(conv.id), "w", encoding="utf-8") as f:
        json.dump(conv.to_dict(), f, indent=2)


def load(conv_id):
    """Load a conversation by id, or return None if it doesn't exist."""
    try:
        with open(_path(conv_id), encoding="utf-8") as f:
            data = json.load(f)
        return Conversation(
            id=data["id"],
            title=data.get("title", ""),
            messages=data.get("messages", []),
            updated=data.get("updated"),
        )
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def list_recent(limit=8):
    """
    Return a list of recent conversations, newest first, as plain dicts:
    {"id", "title", "when"}.
    """
    os.makedirs(CONVERSATIONS_DIR, exist_ok=True)
    convs = []
    for name in os.listdir(CONVERSATIONS_DIR):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(CONVERSATIONS_DIR, name), encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        convs.append(data)

    convs.sort(key=lambda d: d.get("updated", 0), reverse=True)
    result = []
    for d in convs[:limit]:
        when = datetime.fromtimestamp(d.get("updated", 0)).strftime("%b %d")
        result.append({
            "id": d["id"],
            "title": d.get("title") or "(untitled)",
            "when": when,
        })
    return result


def latest_or_new():
    """Resume the most recent conversation, or start a new one if none exist."""
    recent = list_recent(limit=1)
    if recent:
        conv = load(recent[0]["id"])
        if conv:
            return conv
    return new_conversation()

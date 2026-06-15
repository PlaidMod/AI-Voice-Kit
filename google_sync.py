"""
Save found opportunities into a Google Sheet.

Setup (done once with google_auth.py) produces google_token.json. This module
just reads that token and appends a row whenever the model decides to save an
opportunity.

Each saved row is:  date | name | deadline | eligibility | link | why it fits
"""

from datetime import date

from config import GOOGLE_SHEET_ID, GOOGLE_TOKEN_PATH

# The Sheets API libraries are optional -- the rest of Scout works without them.
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    AVAILABLE = True
except Exception:
    AVAILABLE = False

# We only need permission to edit spreadsheets.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_service = None  # cached Sheets API client


def is_configured():
    """True only if the libraries, a token file, and a sheet id are all present."""
    import os
    return AVAILABLE and GOOGLE_SHEET_ID and os.path.exists(GOOGLE_TOKEN_PATH)


def _get_service():
    global _service
    if _service is not None:
        return _service

    creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_PATH, SCOPES)
    # Refresh the access token if it has expired (we saved a refresh token).
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(GOOGLE_TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    _service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return _service


def append_opportunity(name, deadline="", eligibility="", link="", why=""):
    """
    Append one opportunity as a new row. Returns a short status string that
    gets handed back to the model so it can tell the user what happened.
    """
    if not is_configured():
        return ("Google Sheets isn't set up yet, so I couldn't save that. "
                "Tell the user to finish the Google setup.")
    try:
        row = [[date.today().isoformat(), name, deadline, eligibility, link, why]]
        _get_service().spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range="A1",                       # append after the last filled row
            valueInputOption="USER_ENTERED",
            body={"values": row},
        ).execute()
        return f"Saved '{name}' to the Google Sheet."
    except Exception as e:
        return f"Tried to save '{name}' but the Google Sheet call failed: {e}"

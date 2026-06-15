"""
One-time Google sign-in.

Run this ONCE to connect your Google account. It opens a browser, asks you to
approve access to your spreadsheets, and saves google_token.json next to this
file. After that, google_sync.py uses that token automatically.

    python3 google_auth.py

You need google_credentials.json (an OAuth "Desktop app" client) in this folder
first -- see the setup steps in the chat.

Headless Pi (no desktop)? Two easy options:
  1. Run this on your laptop with the same google_credentials.json, then copy
     the resulting google_token.json to the Pi (it works from any machine).
  2. SSH in with port forwarding so the browser step can reach the Pi:
         ssh -L 8765:localhost:8765 pi@raspberrypi.local
     then run this script and open the printed URL on your laptop.
"""

from google_auth_oauthlib.flow import InstalledAppFlow

from config import GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def main():
    flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_PATH, SCOPES)
    # Fixed port so the SSH port-forward trick above works.
    creds = flow.run_local_server(port=8765)
    with open(GOOGLE_TOKEN_PATH, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    print(f"Success! Saved token to {GOOGLE_TOKEN_PATH}")


if __name__ == "__main__":
    main()

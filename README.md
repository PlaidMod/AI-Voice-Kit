# Scout — AIY Voice Kit V1 Opportunity Scout

A custom voice assistant for the **Google AIY Voice Kit V1** (Raspberry Pi 3B +
Voice HAT). It replaces the retired Google Assistant with **Claude** and live
**web search**, tuned to help a high school student find research, internships,
competitions, and summer programs — plus research companies for cold outreach
and rubber-duck debug coding problems.

**How it works:** press and hold the button → talk → release → it transcribes
your speech locally with Whisper, asks Claude (with web search), and speaks back
a tight 3–5 bullet answer.

```
Button press ─► LED on ─► record ─► Whisper (local) ─► Claude + web search ─► speak ─► LED off
```

---

## 1. What you need

- Assembled **AIY Voice Kit V1** running the **AIY system image** (Raspbian-based, Python 3).
- The kit working: speaker plays sound, button + LED respond, mics record.
- An **Anthropic API key** — get one at https://console.anthropic.com (Settings → API Keys).
- Internet access on the Pi (web search needs it).

> Quick hardware check (on the Pi): the AIY image ships with demo scripts under
> `~/AIY-projects-python/src/examples/`. Run the button + audio demos there first
> to confirm the hardware works before setting up Scout.

---

## 2. Get the files onto the Pi

Copy this folder (`main.py`, `system_prompt.txt`, `requirements.txt`,
`README.md`) to the Pi, e.g. to `/home/pi/scout/`. You can use a USB drive,
`scp`, or `git clone` if you put it in a repo.

```bash
# Example with scp, run from your computer:
scp -r "Anthropic Voice Kit"/* pi@raspberrypi.local:/home/pi/scout/
```

---

## 3. Install dependencies

SSH into the Pi (or open a terminal on it) and run:

```bash
cd /home/pi/scout
sudo apt-get update
sudo apt-get install -y ffmpeg        # Whisper needs ffmpeg to read audio
pip3 install -r requirements.txt
```

Heads-up: `openai-whisper` pulls in PyTorch, which is **large and slow** to
install on a Pi 3B (can take 20–40 minutes). Let it finish.

> **If Whisper is too slow on your Pi:** the `tiny` model is much faster than
> `base`. Change `WHISPER_MODEL = "base"` to `"tiny"` near the top of `main.py`.
> For a big speed-up you can later switch to `faster-whisper`, but `openai-whisper`
> is the simplest to start with.

---

## 4. Put your Anthropic API key on the device

Scout reads the key from the `ANTHROPIC_API_KEY` environment variable. **Don't
paste the key into the code** — keep it out of the source files.

The simplest reliable way is a small env file that only your user can read:

```bash
# Create a protected file holding the key
echo 'ANTHROPIC_API_KEY=sk-ant-your-real-key-here' > /home/pi/scout/scout.env
chmod 600 /home/pi/scout/scout.env
```

To run it by hand in a terminal, load that file first:

```bash
cd /home/pi/scout
set -a; . ./scout.env; set +a     # loads ANTHROPIC_API_KEY into this shell
python3 main.py
```

You should hear "Scout is ready." Hold the button, ask something like
*"Find rocketry summer programs for high school sophomores in Houston,"* and
release.

---

## 5. Run automatically at boot with systemd

Once it works by hand, make it start on boot.

Create the service file:

```bash
sudo nano /etc/systemd/system/scout.service
```

Paste this (adjust paths/username if you didn't use `/home/pi/scout`):

```ini
[Unit]
Description=Scout AIY Voice Assistant
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/scout
# Load the API key from the protected env file
EnvironmentFile=/home/pi/scout/scout.env
ExecStart=/usr/bin/python3 /home/pi/scout/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable scout.service     # start on every boot
sudo systemctl start scout.service      # start it now
```

Useful commands:

```bash
sudo systemctl status scout.service     # is it running?
journalctl -u scout.service -f          # watch live logs (what it heard, etc.)
sudo systemctl restart scout.service    # restart after editing main.py
sudo systemctl stop scout.service       # stop it
```

---

## 6. Using Scout

- **Hold the button** while you talk, **release** when done.
- Answers are 3–5 spoken bullets and always end with *"Want me to go deeper on
  any of these?"* — just press the button again and say *"yes, more on the
  second one"* to follow up. Scout remembers the recent conversation.
- Try these:
  - "Find research or internship programs for high school students into aerospace, remote is fine."
  - "Tell me about Firefly Aerospace so I can cold-email them, and give me an email hook."
  - "My Python loop prints the same value every time — help me debug it." (It will ask you a question back.)
  - "What rocketry competitions can a sophomore enter this year?"

---

## 7. Tuning (all near the top of `main.py`)

| Setting | What it does |
|---|---|
| `MODEL` | Which Claude model to use (`claude-sonnet-4-6` by default). |
| `WHISPER_MODEL` | `"tiny"` (fastest) or `"base"` (more accurate). |
| `MAX_RECORD_SECONDS` | Safety cap on recording length. |
| `MAX_TOKENS` | Max length of Claude's reply (kept small for speed). |
| `MAX_WEB_SEARCHES` | How many searches Claude may run per question. |
| `MAX_HISTORY_MESSAGES` | How much conversation to remember before resetting. |

To change Scout's personality or rules, edit **`system_prompt.txt`** — no code
changes needed.

---

## 8. Troubleshooting

- **"ANTHROPIC_API_KEY is not set"** — the env file wasn't loaded. For manual
  runs use the `set -a; . ./scout.env; set +a` line; for systemd check the
  `EnvironmentFile=` path.
- **No sound / can't record** — re-run the AIY hardware demos; Scout can't fix a
  hardware/config problem.
- **Whisper errors about audio** — make sure `ffmpeg` is installed (`apt-get install ffmpeg`).
- **It's slow** — switch `WHISPER_MODEL` to `"tiny"`, lower `MAX_WEB_SEARCHES`,
  and keep questions short. The Pi 3B is the bottleneck, not the network.
- **Watch what it's doing** — `journalctl -u scout.service -f` prints what it
  heard and what it answered.

"""What the player's parts share: its settings (config.json), the way it reaches the Choom app, and the
Portrait's calibration."""
import base64
import json
import os
import string
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # the player's folder
CONFIG_FILE = Path(os.environ.get("GLASS_PLAYER_CONFIG", HERE / "config.json"))


def load_config():
    """config.json (see config.example.json). Missing or broken: the player can't reach the app, so it
    says so and stops."""
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"No {CONFIG_FILE.name}: copy config.example.json to config.json and fill it in.")
    except ValueError as e:
        raise SystemExit(f"{CONFIG_FILE.name} isn't valid JSON: {e}")


CONFIG = load_config()
GLASS_DIR = (HERE / CONFIG.get("glass_dir", "glass")).resolve()  # the page and clips, synced from home
LOGS = HERE / "logs"
PORT = int(CONFIG.get("port", 8765))
CHOOM_URL = str(CONFIG.get("choom_url", "")).rstrip("/")


def choom_headers():
    """For every request to the Choom app: the tunnel's login, and that this is the travel glass (the
    app then speaks a conversation here only when it's open in front of this glass)."""
    headers = {"X-Choom-Glass": "travel", "ngrok-skip-browser-warning": "1"}
    if CONFIG.get("choom_login"):
        headers["Authorization"] = "Basic " + base64.b64encode(str(CONFIG["choom_login"]).encode()).decode()
    return headers


def choom_open(path, body=None, timeout=30, headers=None):
    """A request to the Choom app (JSON when body is a dict); returns the open response."""
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    request = urllib.request.Request(CHOOM_URL + path, data=data, headers={
        **choom_headers(), **({"Content-Type": "application/json"} if isinstance(body, dict) else {}), **(headers or {})})
    return urllib.request.urlopen(request, timeout=timeout)


def find_calibration():
    """The Portrait's visual.json. It's on the Portrait's own USB drive while its USB-C is plugged into
    this computer; a copy is kept in calibration/ for when it's on a wall charger instead (the picture
    only needs HDMI). config.json's "calibration" (a path) overrides both. None if there's neither."""
    if CONFIG.get("calibration"):
        return Path(CONFIG["calibration"])
    if os.name == "nt":
        candidates = [Path(f"{d}:/LKG_calibration/visual.json") for d in string.ascii_uppercase[2:]]
    else:
        candidates = [p for base in ("/media", "/run/media", "/Volumes")
                      for pattern in ("*/LKG_calibration/visual.json", "*/*/LKG_calibration/visual.json")
                      for p in Path(base).glob(pattern)]
    saved = HERE / "calibration"
    for path in candidates:
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                saved.mkdir(exist_ok=True)
                copy = saved / f"{data.get('serial', 'portrait')}_visual.json"
                copy.write_text(json.dumps(data, indent=1), encoding="utf-8")
                return copy
        except (OSError, ValueError):
            continue
    copies = sorted(saved.glob("*_visual.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return copies[0] if copies else None

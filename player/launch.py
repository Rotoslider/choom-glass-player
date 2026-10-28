#!/usr/bin/env python3
"""Start the travel glass: the server, the mic (tower_ears.py, if its packages are installed) and
Chrome full screen on the Portrait. Ctrl+C (or closing this window) stops them all.

Chrome gets a profile of its own, so it never touches your everyday browser: kiosk mode on the
Portrait's screen, Windows' display scaling ignored (the page needs the Portrait's 1536x2048 pixels
one to one), and sound allowed without a click first.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from common import CHOOM_URL, CONFIG, GLASS_DIR, HERE, LOGS, PORT

PORTRAIT = (1536, 2048)
PAGE = f"http://127.0.0.1:{PORT}/living.html"


def portrait_screen():
    """(x, y, width, height) of the Portrait among the screens, or None."""
    screens = []
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # real pixels, not scaled ones
        except Exception:
            user32.SetProcessDPIAware()
        proc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

        def found(monitor, dc, rect, data):
            r = rect.contents
            screens.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
            return 1
        user32.EnumDisplayMonitors(None, None, proc(found), 0)
    elif shutil.which("xrandr"):
        import re
        out = subprocess.run(["xrandr", "--query"], capture_output=True, text=True).stdout
        for w, h, x, y in re.findall(r" connected (?:primary )?(\d+)x(\d+)\+(\d+)\+(\d+)", out):
            screens.append((int(x), int(y), int(w), int(h)))
    return next((s for s in screens if s[2:] == PORTRAIT), None)


def find_chrome():
    if CONFIG.get("chrome"):
        return CONFIG["chrome"]
    if os.name == "nt":
        for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
            exe = Path(base or "") / "Google" / "Chrome" / "Application" / "chrome.exe"
            if base and exe.is_file():
                return str(exe)
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if Path(mac).exists():
        return mac
    return shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")


def ears_ready():
    """The mic's packages are installed (requirements-ears.txt)."""
    return all(importlib.util.find_spec(m) for m in ("numpy", "webrtcvad", "faster_whisper", "sounddevice"))


def start(name, args, env=None):
    LOGS.mkdir(exist_ok=True)
    log = (LOGS / f"{name}.log").open("a", encoding="utf-8")
    log.write(f"== {time.strftime('%Y-%m-%d %H:%M:%S')} start ==\n")
    log.flush()
    return subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=HERE)


def main():
    children = [start("server", [sys.executable, str(HERE / "player" / "server.py")])]
    for _ in range(40):  # up within a few seconds, or it says why in logs/server.log
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/status", timeout=1).read()
            break
        except Exception:
            if children[0].poll() is not None:
                raise SystemExit("The server stopped; see logs/server.log.")
            time.sleep(0.25)

    mic = CONFIG.get("mic", {})
    if mic.get("off"):
        print("mic: off (config.json)")
    elif not ears_ready():
        print("mic: not started (install requirements-ears.txt to talk to them here)")
    elif not (GLASS_DIR / "tower_ears.py").is_file():
        print("mic: no tower_ears.py in the glass folder (sync again)")
    else:
        env = {**os.environ, "CHOOM_URL": CHOOM_URL, "CHOOM_GLASS": "travel", "HOLOGRAM_URL": f"http://127.0.0.1:{PORT}",
               "EARS_DEVICE": mic.get("device", "cpu"), "EARS_COMPUTE": mic.get("compute", "int8"),
               "EARS_MODEL": mic.get("model", "small.en"), "EARS_MIC": mic.get("name", "EMEET")}
        if CONFIG.get("choom_login"):
            env["CHOOM_AUTH"] = str(CONFIG["choom_login"])
        children.append(start("ears", [sys.executable, str(GLASS_DIR / "tower_ears.py")], env))
        print(f"mic: listening ({env['EARS_MIC']}, Whisper {env['EARS_MODEL']} on the {env['EARS_DEVICE']})")

    chrome, screen = find_chrome(), portrait_screen()
    if not chrome:
        print(f"Chrome not found: set \"chrome\" in config.json, or open {PAGE} yourself.")
    else:
        args = [chrome, f"--user-data-dir={HERE / '.chrome-profile'}", f"--app={PAGE}", "--kiosk",
                "--force-device-scale-factor=1", "--autoplay-policy=no-user-gesture-required",
                "--no-first-run", "--no-default-browser-check", "--noerrdialogs", "--disable-session-crashed-bubble",
                "--disable-features=Translate"]
        if screen:
            # Its middle, so the window lands on the Portrait whether Chrome counts in real or scaled
            # pixels; kiosk mode then fills that screen.
            x, y, w, h = screen
            args.append(f"--window-position={x + w // 2 - 50},{y + h // 2 - 50}")
            print(f"glass: Chrome on the Portrait at {x},{y}")
        else:
            print("glass: no 1536x2048 screen found; Chrome opens on the main one (drag it over, F11)")
        children.append(start("chrome", args))

    print("Running. Ctrl+C here stops the travel glass.", flush=True)
    try:
        while children[0].poll() is None:
            time.sleep(1)
        print("The server stopped; see logs/server.log.")
    except KeyboardInterrupt:
        pass
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()


if __name__ == "__main__":
    main()

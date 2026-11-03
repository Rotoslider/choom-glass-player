#!/usr/bin/env python3
"""Start the travel glass: the server, the mic (tower_ears.py, if its packages are installed) and
Chrome full screen on the Portrait. Ctrl+C (or closing this window) stops them all, the glass window
included.

Chrome is a program of its own: closing the start window doesn't close it, and a Chrome already running
on the player's profile opens each new start as one more window. So stopping closes the glass window,
and starting first closes any glass window an earlier start left open. A second start while one is
running says so and leaves it be.

Chrome gets a profile of its own, so it never touches your everyday browser: kiosk mode on the
Portrait's screen, Windows' display scaling ignored (the page needs the Portrait's 1536x2048 pixels
one to one), and sound allowed without a click first.
"""
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from common import CHOOM_URL, CONFIG, GLASS_DIR, HERE, LOGS, PORT

PORTRAIT = (1536, 2048)
PAGE = f"http://127.0.0.1:{PORT}/living.html"
PROFILE = HERE / ".chrome-profile"  # Chrome's own profile for the glass; nothing else uses it


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


def glass_chrome():
    """PIDs of every Chrome process on the glass's profile (its windows and their helpers)."""
    mine = str(PROFILE).lower()
    if os.name == "nt":
        # No double quotes inside: Windows would have to escape them on the way to PowerShell.
        script = ("Get-CimInstance -ClassName Win32_Process -Filter 'Name = ''chrome.exe''' | "
                  "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                 capture_output=True, text=True, timeout=30,
                                 creationflags=0x08000000).stdout.strip()  # CREATE_NO_WINDOW
            rows = json.loads(out) if out else []
        except Exception as e:
            print(f"glass: couldn't look for an earlier glass window ({type(e).__name__})")
            return []
        rows = [rows] if isinstance(rows, dict) else rows
        return [int(r["ProcessId"]) for r in rows if mine in str(r.get("CommandLine") or "").lower()]
    try:
        out = subprocess.run(["ps", "-A", "-ww", "-o", "pid=", "-o", "args="], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return []
    pids = []
    for line in out.splitlines():
        pid, _, args = line.strip().partition(" ")
        if pid.isdigit() and int(pid) != os.getpid() and mine in args.lower():
            pids.append(int(pid))
    return pids


def close_chrome(pids):
    """Close those Chrome processes and wait until they're gone (a Chrome still closing on the profile
    would take the next start's window as one of its own)."""
    if not pids:
        return
    if os.name == "nt":
        # Directly, not through taskkill: this also runs while the start window is closing, when a new
        # console program may not start. Chrome's helpers end with its main process.
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handles = []
        for pid in pids:
            handle = kernel32.OpenProcess(0x00100001, False, pid)  # SYNCHRONIZE | PROCESS_TERMINATE
            if handle:
                kernel32.TerminateProcess(handle, 1)
                handles.append(handle)
        for handle in handles:
            kernel32.WaitForSingleObject(handle, 5000)
            kernel32.CloseHandle(handle)
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in pids:
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        deadline = time.time() + 5
        while time.time() < deadline:
            alive = []
            for pid in pids:
                try:
                    os.waitpid(pid, os.WNOHANG)  # reaped, if it's this start's own Chrome
                except ChildProcessError:
                    pass
                try:
                    os.kill(pid, 0)
                    alive.append(pid)
                except OSError:
                    pass
            if not (pids := alive):
                return
            time.sleep(0.1)


def player_running():
    """A player's server already answers on the port (another start window)."""
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/status", timeout=1).read()
        return True
    except Exception:
        return False


def on_window_close(stop):
    """On Windows, closing the start window ends Python without running its finally: blocks; a console
    handler gets a few seconds to stop everything first."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    def handler(kind):
        if kind in (2, 5, 6):  # the window closed, logoff, shutdown
            stop()
            return True
        return False  # Ctrl+C: Python's own KeyboardInterrupt, then stop() in main's finally:
    on_window_close.handler = handler  # kept for as long as Python runs
    try:
        ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)
    except Exception:
        pass


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
    if player_running():
        raise SystemExit("The travel glass is already running in another start window. Use that one, or close it\n"
                         "and start again.")
    leftover = glass_chrome()
    if leftover:
        close_chrome(leftover)
        print("glass: closed the glass window an earlier start left open")

    children, stopped = [], []

    def stop():
        """Everything this start began, the glass window first, then anything else on its profile."""
        if stopped:
            return
        stopped.append(True)
        for child in reversed(children):
            if child.poll() is None:
                if child is chrome_child:
                    close_chrome([child.pid])
                else:
                    child.terminate()
        close_chrome(glass_chrome())

    chrome_child = None
    on_window_close(stop)
    children.append(start("server", [sys.executable, str(HERE / "player" / "server.py")]))
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
        args = [chrome, f"--user-data-dir={PROFILE}", f"--app={PAGE}", "--kiosk",
                "--force-device-scale-factor=1", "--autoplay-policy=no-user-gesture-required",
                "--no-first-run", "--no-default-browser-check", "--noerrdialogs",
                "--disable-session-crashed-bubble", "--hide-crash-restore-bubble", "--disable-features=Translate"]
        if screen:
            # Its middle, so the window lands on the Portrait whether Chrome counts in real or scaled
            # pixels; kiosk mode then fills that screen.
            x, y, w, h = screen
            args.append(f"--window-position={x + w // 2 - 50},{y + h // 2 - 50}")
            print(f"glass: Chrome on the Portrait at {x},{y}")
        else:
            print("glass: no 1536x2048 screen found; Chrome opens on the main one (drag it over, F11)")
        chrome_child = start("chrome", args)
        children.append(chrome_child)

    print("Running. Ctrl+C here stops the travel glass.", flush=True)
    try:
        while children[0].poll() is None:
            time.sleep(1)
        print("The server stopped; see logs/server.log.")
    except KeyboardInterrupt:
        pass
    finally:
        stop()


if __name__ == "__main__":
    main()

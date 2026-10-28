#!/usr/bin/env python3
"""The travel glass's server, for the glass page in Chrome and for tower_ears.py, on this computer only
(127.0.0.1). It serves the page and clips synced from home (glass/), the Portrait's calibration, and
the Choom app's live feed, her voice and her pictures, reached through the app's tunnel.

The feed is the one the glass at home follows. Each spoken sentence carries `speakTravel`, true when
the conversation is open in a browser in front of this glass (the app knows it by the address) or was
begun at its mic; the page here speaks those and no others. Camera and glass requests are left to the
glass at home.
"""
import base64
import collections
import http.server
import json
import mimetypes
import queue
import re
import sys
import threading
import time
import urllib.parse
from pathlib import Path

from common import CHOOM_URL, CONFIG, GLASS_DIR, LOGS, PORT, choom_open, find_calibration

# The page's look on a laptop: fewer views and no smoothing (Iris Xe ran 30 fps with these, 3 with
# the home glass's 48 views and smoothing). config.json "page" adds to or overrides them.
PAGE_SETTINGS = {"views": 32, "smoothing": False, **CONFIG.get("page", {})}
TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json", ".mp4": "video/mp4",
         ".html": "text/html", ".glb": "model/gltf-binary", ".wasm": "application/wasm"}
IMAGE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
LOG_MAX_BYTES = 20_000_000
FEED_CHECK_S = 45  # the app pings its feed every 15 s

clients, clients_lock = set(), threading.Lock()
log_lock = threading.Lock()
latest, received_at = {}, {}   # the page's (and tower_ears') latest entry of each kind, and when
app_mute = {}                  # the app's mute, for a page that connects after it was pressed
feed = {"state": "starting"}
chat_turns = {}                # (Choom, chat or group, its id) -> when her turn there started
tower_talk = {"open": False, "at": 0.0}
image_cache = {}
heartbeat_now = threading.Event()
SPOKEN_S = 90                  # what she said this long ago may still come back to the mic
spoken = collections.deque(maxlen=30)  # (when, sentence) spoken here, for tower_ears' echo guard


def write_log(entry):
    """One JSON line in logs/telemetry.log, kept under 20 MB with one old log."""
    LOGS.mkdir(exist_ok=True)
    log = LOGS / "telemetry.log"
    with log_lock:
        try:
            if log.stat().st_size > LOG_MAX_BYTES:
                log.replace(log.with_suffix(".log.1"))
        except FileNotFoundError:
            pass
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


def note(entry):
    entry.setdefault("time", time.strftime("%Y-%m-%dT%H:%M:%S"))
    write_log(entry)


def broadcast(event):
    data = json.dumps(event)
    with clients_lock:
        for q in clients:
            q.put(data)


def follow_choom():
    """Pass the app's /api/hologram/events on to the page, as speakTravel says; reconnect when it drops.
    After a drop the page hears "reconnected": a turn whose end was lost with it would leave her
    thinking until the next one."""
    dropped = False
    while True:
        try:
            with choom_open("/api/hologram/events", timeout=FEED_CHECK_S, headers={"Accept": "text/event-stream"}) as response:
                feed.update(state="connected", since=time.strftime("%H:%M:%S"))
                if dropped:
                    broadcast({"type": "feed", "state": "reconnected"})
                    note({"kind": "feed", "state": "reconnected"})
                    dropped = False
                last_kind = {}
                for raw in response:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except ValueError:
                        continue
                    kind = event.get("type")
                    # Her reasoning comes one "thinking" event per token; the page only needs the first.
                    key = (event.get("choom"), event.get("chatId"))
                    if kind == "thinking" and last_kind.get(key) == "thinking":
                        continue
                    last_kind[key] = kind
                    if kind in ("camera_request", "glass_request"):
                        continue  # the glass at home answers these
                    if kind == "mute" and isinstance(event.get("muted"), bool):
                        app_mute["muted"] = event["muted"]
                    if kind == "content":
                        event["speak"] = event.get("speakTravel") is True
                        if event["speak"] and isinstance(event.get("text"), str):
                            spoken.append((time.time(), event["text"]))
                    if event.get("source") in ("chat", "group") and event.get("choom"):
                        turn = (event["choom"], event["source"], event.get("chatId") or event.get("roomId"))
                        if kind == "turn_start":
                            chat_turns[turn] = time.time()
                        elif kind in ("turn_end", "error"):
                            chat_turns.pop(turn, None)
                    broadcast({**event, "type": "choom", "event": kind})
        except Exception as e:  # no network, the tunnel or the app restarting, a wrong login
            state = f"disconnected ({type(e).__name__}{': ' + str(e.code) if hasattr(e, 'code') else ''})"
            if feed.get("state") != state:
                note({"kind": "feed", "state": state})
            feed["state"] = state
        dropped = True
        time.sleep(3)


def voice_heartbeat():
    """Every 10 s, tell the app whether this glass is speaking for the Chooms (the page running with
    its voice on). A browser in front of it then stays quiet and hands it the conversation."""
    while True:
        status = latest.get("status") or {}
        voice = bool(time.time() - received_at.get("status", 0) < 10 and status.get("voiceOn"))
        try:
            choom_open("/api/hologram/voice", {"voice": voice}, timeout=10).read()
            feed["voice_handoff"] = voice
        except Exception as e:
            feed["voice_handoff"] = f"failed ({type(e).__name__})"
        heartbeat_now.wait(10)
        heartbeat_now.clear()


def synthesize(text, voice):
    """WAV bytes of `text` in her voice, from the app (which cleans the text and runs Chatterbox)."""
    with choom_open("/api/tts", {"text": text, "voice": voice}, timeout=90) as response:
        result = json.loads(response.read())
    if not result.get("success") or not result.get("audio"):
        raise RuntimeError(result.get("error") or "no audio")
    return base64.b64decode(result["audio"])


def choom_image(image_id):
    """A picture from the app's gallery as plain image bytes for the page (the app keeps images as data
    URIs); the last few are kept."""
    if image_id not in image_cache:
        with choom_open(f"/api/images/{image_id}", timeout=30) as response:
            record = json.loads(response.read())
        url = record.get("imageUrl") or (record.get("image") or {}).get("imageUrl") or ""
        match = re.match(r"data:(image/[\w.+-]+);base64,(.*)", url, re.S)
        if match:
            image_cache[image_id] = (match.group(1), base64.b64decode(match.group(2)))
        elif url:
            path = urllib.parse.urlparse(urllib.parse.urljoin(CHOOM_URL + "/", url)).path
            with choom_open(path, timeout=30) as response:
                image_cache[image_id] = (response.headers.get_content_type(), response.read())
        else:
            raise ValueError("no image in the record")
        while len(image_cache) > 6:
            image_cache.pop(next(iter(image_cache)))
    return image_cache[image_id]


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body, ctype="application/json", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        return self._send(json.dumps(obj).encode(), code=code)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urllib.parse.unquote(self.path.split("?")[0])
        if path in ("/", "/index.html"):
            self.send_response(302)
            self.send_header("Location", "/living.html")
            self.end_headers()
            return
        if path == "/calibration.json":
            cal = find_calibration()
            if not cal:
                return self._json({"error": "no calibration: plug the Portrait's USB-C into this computer once"}, 404)
            return self._send(cal.read_bytes())
        if path == "/glass-settings.json":
            return self._json(PAGE_SETTINGS)
        if path == "/status":
            talking = tower_talk["open"] and time.time() - tower_talk["at"] < 180
            return self._json({**latest, "choom_feed": feed, "tower_conversation": {"open": talking},
                               "spoken": [text for at, text in list(spoken) if time.time() - at < SPOKEN_S],
                               "chat_turns": sorted({c for (c, source, _), at in chat_turns.items()
                                                     if source == "chat" and time.time() - at < 600})})
        if path == "/events":
            return self._events()
        if path.startswith("/choom-image/"):
            image_id = path.removeprefix("/choom-image/")
            if not IMAGE_ID.fullmatch(image_id):
                return self.send_error(404)
            try:
                ctype, body = choom_image(image_id)
            except Exception as e:
                return self._json({"error": str(e)}, 502)
            return self._send(body, ctype)
        return self._file(path)

    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        q = queue.Queue()
        if "muted" in app_mute:  # what a page that just started can't know yet
            q.put(json.dumps({"type": "mute", "muted": app_mute["muted"]}))
        with clients_lock:
            clients.add(q)
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    self.wfile.write(f"data: {q.get(timeout=15)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except OSError:
            pass
        finally:
            with clients_lock:
                clients.discard(q)

    def _file(self, path):
        """A file of the synced glass, with byte ranges (video seeking needs them)."""
        rel = path.lstrip("/")
        f = (GLASS_DIR / rel).resolve()
        if ".." in rel.split("/") or GLASS_DIR not in f.parents or not f.is_file() or f.name.startswith("."):
            return self.send_error(404)
        ctype = TYPES.get(f.suffix) or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        size = f.stat().st_size
        start, end = 0, size - 1
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start, end = int(m.group(1)), int(m.group(2)) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with f.open("rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0 and (chunk := fh.read(min(1 << 20, left))):
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except OSError:
            pass  # the page moved on (a seek, the next clip)

    def do_POST(self):
        try:
            entry = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.send_error(400)
        if self.path == "/log":  # the page's telemetry; its status every 2 s
            entry.setdefault("time", time.strftime("%Y-%m-%dT%H:%M:%S"))
            kind = entry.get("kind", "unknown")
            if kind == "status" and (latest.get("status") or {}).get("voiceOn") not in (None, entry.get("voiceOn")):
                heartbeat_now.set()  # voice switched on or off: tell the app now
            latest[kind], received_at[kind] = entry, time.time()
            write_log(entry)
            return self._json({})
        if self.path == "/speak":
            text = str(entry.get("text", ""))
            try:
                return self._send(synthesize(text, entry.get("voice") or "sophie"), "audio/wav")
            except Exception as e:
                note({"kind": "speak", "chars": len(text), "error": f"{type(e).__name__}: {e}"})
                return self._json({"error": str(e)}, 502)
        if self.path == "/ears":
            return self._ears(entry)
        if self.path == "/control":  # by hand, as at home: {"choom": "genesis"}, {"action": "next"}
            broadcast({**entry, "type": "control"})
            return self._json({})
        return self.send_error(404)

    def _ears(self, entry):
        """tower_ears.py: "OK Genesis" heard at this glass's mic. The page shows her listening and brings
        her to the glass. Only events are logged, never what was said."""
        event, choom = entry.get("event"), entry.get("choom")
        if event in ("wake", "window", "invited") or (event == "listen" and entry.get("listening") is True):
            tower_talk.update(open=True, at=time.time())
        elif event in ("window_closed", "invited_done") or (event == "listen" and entry.get("listening") is False):
            tower_talk.update(open=False, at=time.time())
        elif event != "voice":
            tower_talk["at"] = time.time()
        if event in ("window", "window_closed"):  # the reply window opening, or closing unheard
            broadcast({"type": "control", "chime": "open" if event == "window" else "close"})
        if event == "voice":  # someone is talking nearby: no screensaver turn now
            broadcast({"type": "control", "activity": True})
            return self._json({})
        if event in ("wake", "listen"):
            broadcast({"type": "choom", "event": "listening", "source": "mic", "tower": True,
                       "wake": event == "wake", "group": choom == "Chooms",
                       "listening": event == "wake" or entry.get("listening") is True,
                       "choom": choom, "chatId": None, "roomId": None})
        latest["ears"], received_at["ears"] = entry, time.time()
        note({"kind": "ears", "event": event, "choom": choom,
              **{k: entry[k] for k in ("message", "seconds", "voiced", "ended", "floor", "echo") if k in entry}})
        return self._json({})


def main():
    if not CHOOM_URL:
        raise SystemExit('config.json has no "choom_url" (the Choom app\'s tunnel address).')
    if not (GLASS_DIR / "living.html").is_file():
        raise SystemExit(f"No glass page in {GLASS_DIR}: run the sync first (sync.bat or player/sync.py).")
    for target in (follow_choom, voice_heartbeat):
        threading.Thread(target=target, daemon=True).start()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    note({"kind": "server", "event": "start", "port": PORT, "calibration": str(find_calibration() or "none")})
    print(f"glass server on http://127.0.0.1:{PORT}/living.html", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()

# choom-glass-player

A travel glass for the Chooms. It plays their living holograms on a second Looking Glass Portrait from
an ordinary laptop, with their voices, lip sync, and a speakerphone to talk to them ("OK Genesis, ...").

The holograms are made at home, on the machine with the big GPU: the clips, their depth and the glass
page live in the [Choom](https://github.com/Rotoslider/Choom) repo's `hologram/` folder (and its Glass
Studio). This player only plays them. Before a trip it copies them from the home glass, and on the road
it follows the Choom app from away, over Tailscale (or a tunnel).

## What you need

- **A Looking Glass Portrait.** HDMI carries the picture. Its USB-C gives it power and, plugged into the
  laptop at least once, lets the player read its calibration (a copy is kept, so a wall charger works
  after that).
- **A laptop** with Google Chrome and Python 3.10 or newer. Windows 11 is the main target; Linux and a
  Mac should work too. Intel Iris Xe (a Dell Latitude 7230) runs it at 30 fps with 32 views and no
  smoothing.
- **The Choom app** running at home, reachable from away. [Tailscale](https://tailscale.com) is the
  easy way: free for personal use, no data cap, and no static address or port forwarding needed (it
  works behind Starlink). Install it on the computer running the Choom app and on the laptop, signed
  in to the same account. A tunnel such as ngrok works too, but its free plan has 1 GB a month, and
  the Choom web app alone can use that in an hour (each time it opens a long chat it downloads all of it).
- **The home glass** (the Choom repo's `hologram/`), to sync from.
- **Optional: a USB speakerphone** (an EMEET OfficeCore, as on the home glass) to talk to them.

## Setup (Windows)

1. Install Python from python.org (tick **Add python.exe to PATH**) and Google Chrome.
2. Get this folder: `git clone https://github.com/Rotoslider/choom-glass-player`, or download it as a zip.
3. For the mic, in the folder: `py -3 -m venv .venv`, then `.venv\Scripts\pip install -r requirements-ears.txt`.
   The first start downloads the Whisper model (a few hundred MB). Without the mic, skip this step.
4. Copy `config.example.json` to `config.json` and fill in:
   - `choom_url`: the Choom app from away. Over Tailscale it's the app computer's Tailscale name and the
     app's port, e.g. `http://my-mac:3000`; through a tunnel, the tunnel's address.
   - `choom_login`: only for a tunnel with a login, as `user:password`; leave it out over Tailscale.
   - `share_url`: the home glass and port 8770, e.g. `http://192.168.1.23:8770`.

   `config.json` stays out of git: it can hold a login.
5. Plug in the Portrait: HDMI, and its USB-C into the laptop for the first start.

## Before a trip: sync

1. On the home glass, start the share: `python3 hologram/tools/share_glass.py` (it stops by itself after 3 hours).
2. On the laptop, at home, run `sync.bat`.

The first sync copies about 11 GB: the page, the mic's script, and each Choom's clips. After that only
what changed is copied. Run it again after new clips are built at home.

## On the road

Run `start.bat`. It starts the server, the mic and Chrome, full screen on the Portrait. Close its window
to stop the travel glass.

- **Talk at it.** Say "OK Genesis, ..." (or Aloy, Optic or Eve), or "OK Chooms" for the group room. Her
  answer comes from the glass.
- **Or use the Choom app on the laptop.** Open it in a browser through the tunnel. The chat you have
  open is spoken by the glass, and the browser stays quiet.
- **The glass at home stays quiet** meanwhile: nobody at home has those conversations open.

## Settings

Everything else in `config.json` has a default and can be left out:

| Setting | Default | What it does |
|---|---|---|
| `page` | `{"views": 32, "smoothing": false, "campfire": false}` | the page's [install settings](https://github.com/Rotoslider/Choom/blob/main/hologram/docs/reference.md#looks-and-outfits): with `campfire` off the group stays on the standing stage after dark (three seated Chooms and the fire lag on a laptop); `48`, `true` and `true` are the home glass's, for a bigger GPU |
| `mic` | `{"name": "EMEET", "device": "cpu", "compute": "int8", "model": "small.en"}` | part of the mic's name, and where Whisper runs (`"device": "cuda"` with an NVIDIA GPU); `"off": true` starts no mic |
| `glass_dir` | `glass` | where the sync puts the page and clips |
| `port` | `8765` | the player's own address, on this computer only |
| `chrome` | found | the path to chrome.exe, if it isn't in the usual place |
| `calibration` | found | a path to the Portrait's `visual.json`, if it can't be read from the Portrait |

## Troubleshooting

- **No sound.** When a display is plugged in over HDMI, Windows often makes it the sound output. Click
  the speaker icon by the clock and pick the laptop's speakers or the speakerphone.
- **Plug the speakerphone in by USB, not Bluetooth.** When an app opens a Bluetooth speakerphone's mic,
  Windows switches it to its hands-free mode, a different device, and both the mic and the sound lose
  it. Over USB its echo cancelling also keeps her voice out of its own mic. If the mic named in
  `config.json` isn't there, the player waits for it rather than use another one (the laptop's own mic
  would hear her).
- **Loud static from the speakerphone** while she talks, though it played cleanly before: unplug its USB
  and plug it back in. (It happened once, after the player was restarted; a replug cleared it.)
- **She answers herself.** The mic is hearing her: her voice is coming out of something other than the
  speakerphone (the laptop's speakers). Make the speakerphone the sound output. The player also drops
  what the mic hears when it's mostly her own last words, but echo cancelling is the real fix.
- **The 3D looks wrong, or different off to the side.** The page has to fill the Portrait pixel for pixel.
  The player sets Chrome's scaling to 1x itself. If Chrome didn't land on the Portrait, drag it there
  and press F11.
- **She doesn't move or talk.** Open `http://127.0.0.1:8765/status`. `choom_feed` says whether the feed
  is connected. `disconnected (URLError)` means the app can't be reached: is Tailscale on, on both? A
  tunnel answering `HTTPError: 401` means the login in `config.json` is wrong.
- **Tailscale stopped working after months.** Its sign-in on each device lasts 180 days by default. In
  Tailscale's admin console, turn off key expiry for the app's computer and the laptop before a trip.
- **Logs** are in `logs/`: `server.log`, `ears.log` and `chrome.log` from each part, and `telemetry.log`
  with the page's own lines (its frame rate every 2 s, lip-sync timing, the mic's events; never what was
  said).

## What it leaves to the glass at home

There's no camera (eye contact, his face at the desk), no Home Assistant presence or weather, and no
welcome back. The Chooms' own requests to the glass (an outfit they ask for, a move) are answered by the
glass at home.

## How it works

- **`player/server.py`** serves the synced page and clips to Chrome and to the mic, on 127.0.0.1 only. It
  follows the app's live feed (`/api/hologram/events`) and passes on her voice (`/api/tts`) and her
  pictures. Every request to the app carries `X-Choom-Glass: travel` (and a tunnel's login, if set).
  The app knows the laptop is away from home by its address (Tailscale's, or the tunnel's).
- **The app** marks each sentence `speak` (open in a browser at home) and `speakTravel` (open in a browser
  at this glass's address, or begun at its mic). The player speaks only `speakTravel`.
- **Every 10 s** the server tells the app that this glass has the voice, so a browser in front of it stays
  quiet.
- **`tower_ears.py`** (synced from home) is the home glass's mic, recording through PortAudio here.
- **`player/sync.py`** copies from the home glass's `tools/share_glass.py`. **`player/launch.py`** starts
  everything.

The server, sync and launcher use only Python's standard library; the mic needs `requirements-ears.txt`.
More in the Choom repo: [Travel glass](https://github.com/Rotoslider/Choom/blob/main/hologram/docs/reference.md#travel-glass).

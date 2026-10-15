# tapedeck

Spotify client for HAVEN, in the style of a Win98 desktop utility with a cassette-deck display. Status: **1.0, shipped**: playlists, Liked Songs, search, the queue, artist and album pages, artist radio, album art on the display, spinning reels, real VU meters, MPRIS and media keys, a menu entry and an engine user service. See [PLAN.md](PLAN.md).

## Setup
1. librespot: `cargo install librespot --version 0.8.0 --locked --no-default-features --features rustls-tls-native-roots`
2. Spotify developer app with redirect URI `http://127.0.0.1:8898/callback`, then `python3 -m tapedeck.cli setup <client_id>` and `python3 -m tapedeck.cli login`
3. First engine run: `bin/tapedeck-engine` once in a terminal (it opens the browser for librespot's own login), then Ctrl+C
4. `bin/tapedeck-install`: the menu entry, the engine's systemd user service (`systemd/tapedeck-engine.service`, symlinked into `~/.config/systemd/user/`) and the VT323 font

## Run
**TAPEDECK** in the XFCE menu (Multimedia), or `bin/tapedeck`. The deck starts the engine service (`systemctl --user start tapedeck-engine`) if it isn't running and stops it again on exit. The Connect device is online about 2.7 s after launch. The service restarts librespot if it crashes, and its log is `journalctl --user -u tapedeck-engine`. Without the service installed, the deck runs `bin/tapedeck-engine` itself and logs to `$XDG_RUNTIME_DIR/tapedeck/engine.log`.

To keep TAPEDECK available as a Spotify Connect speaker from login (to cast from a phone with the deck closed): `systemctl --user enable --now tapedeck-engine`. Idle, it costs about 24 MB and 0 % CPU. An engine the deck didn't start is left running when the deck exits.

Closing the window docks the deck in the panel's systray and the music keeps playing. Hidden there it costs the same as minimized (~1 % CPU). Left-click the tray icon to show or hide the deck, right-click for play/pause, next, previous and Exit; hover shows the current track. Only Exit (or `Ctrl+Q`) quits. Without a systray, closing quits.

The LCD uses the VT323 pixel font from `~/haven/shared/fonts/` (installed into `~/.local/share/fonts/`).

## Keys
`Space` play/pause · `S` stop · `H`/`L` previous/next · `Shift+H`/`Shift+L` seek ±10 s · `+`/`-` volume · `E` eject (drawer) · `/` search · `Enter` play selected / open page · `Q` queue selected · `A`/`B` artist / album page · `R` radio · `Backspace` (or `Alt+Left`) back · `Esc` leave search · `?` keyboard card · `Ctrl+Q` exit

## Browsing and radio
Press `A` or `B` on a track, or click the artist line or the J-card on the display, to open an artist or album page. An artist page lists Popular tracks, Albums, EPs, Singles and Fans Also Like. Every column keeps its meaning on every row (album rows: name and year under Title, the album's artists under Artist). The release type is in the section heading, and details are in the tooltip. Pages join the Cassette list, and Back walks the history.

Spotify withholds top tracks, related artists, recommendations and radio (`spotify:station:`) from development-mode apps. TAPEDECK gets those from **Deezer's public API** (no key, no account) and matches each song back to Spotify by search. A match must agree on the artist and the title; a song Spotify doesn't have is dropped rather than replaced by a wrong one (typically 22–25 of 25 radio tracks match). Starting radio takes about 4 s. Started from the song in the deck, the song keeps playing and the station follows. The engine also runs with `--autoplay on`, so when a tape ends, Spotify keeps playing similar music.

## Life
- **Reels** turn at the speed of real tape (4.76 cm/s), so the nearly empty reel spins faster than the full one, and both spin backwards while the tape is loading. 10 fps; `TAPEDECK_FPS=15` for smoother reels.
- **VU meters** show TAPEDECK's own stream, not the system mix: `parec --monitor-stream` on the engine's sink input, at 8 kHz. The level is corrected for librespot's volume, so the meters show the level on the tape, like a real deck. 24 segments from -36 dB to 0 dB, rising at once and falling over about 0.6 s.
- Reels, meters and parec only run while the tape plays in a visible window. When paused, minimized or on another workspace, the UI uses no CPU and parec isn't running.
- The display renders into a client-side image, and animation frames redraw only the reels and meter bars. Drawing straight to the window made Xorg rasterize every arc.

## Media keys and MPRIS
TAPEDECK is an MPRIS player (`org.mpris.MediaPlayer2.tapedeck`). Media keys, Bluetooth headphone buttons (through `mpris-proxy`) and MPRIS applets see the track, cover and position, and can play, pause, skip, seek and set the volume. The MacBook's F7/F8/F9 (XF86AudioPrev/Play/Next, plus Stop) are bound in xfce4-keyboard-shortcuts to `bin/tapedeck-key`, which sends to TAPEDECK, or to another MPRIS player when TAPEDECK isn't running. The shortcuts file from before the binding is backed up in `~/.local/share/xfce-keys-backup/`.

## Remote control
D-Bus actions for hotkeys and scripts: `play-pause next previous stop eject artist album radio`, e.g.
`gdbus call --session --dest cc.haunts.haven.tapedeck --object-path /cc/haunts/haven/tapedeck --method org.gtk.Actions.Activate next [] {}`

## Cache
`~/.cache/haven/tapedeck/` holds `playlists.json`, `liked.json`, `tapes/<id>.json` (your own playlists, keyed by snapshot_id) `sealed/<id>.json` (tracks heard on followed playlists) and `art/` (covers: 64 px, dithered to the web-safe palette, about 4 KB each). It's safe to delete.

## Test commands
`python3 -m tapedeck.cli devices | search <q> | playlists | play [uri] | pause | next | previous | now`

## Measured (1.0, 2026-10-13, 160 kbps, engine under systemd)
Per process, % of one core, sampled from /proc over 20–60 s. The Xorg baseline from other windows (mostly the terminal) is 0–5 % on its own, so the Xorg numbers are approximate.

| state | UI | Xorg | xfwm4 | librespot | pacat | parec | total |
|---|---|---|---|---|---|---|---|
| playing, visible, 60 s | 3.2 % | 3.5 % | 1.1 % | 1.3 % (3.9 % across a track change) | 0.2 % | 0.3 % | ~10 % |
| playing, minimized | 0 % | (baseline) | 0.5 % | 0.9 % | 0.1 % | — | ~1 % |
| paused, visible | 0–0.2 % | (baseline) | 0 % | 0 % | 0 % | — | ~0 % |

| | RSS |
|---|---|
| UI | 76–78 MB |
| librespot | 21–24 MB |
| pacat, parec | 5 MB each (pacat only while playing) |

### Against the targets
| target | measured | |
|---|---|---|
| UI RSS < 70 MB | 76–78 MB | over: mostly GTK at 2x HiDPI scale; the drawer's lists add ~2 MB |
| librespot RSS < 30 MB | 21–24 MB | ✅ |
| CPU idle (paused / hidden) ≈ 0 % | 0 % | ✅ |
| CPU playing, visible < 8 % (reels 15 fps, VU 20 Hz) | ~10 % at 10 fps | over: UI side (UI + Xorg + xfwm4 + parec) ~8 %, engine ~1.5 % |
| CPU playing, minimized < 3 % | ~1 % | ✅ |

Animation is the expensive part: almost all of it is GTK's per-frame overhead and the compositor, since a frame draws in about 1 ms. Drawing straight to the X window cost ~12 % at 15 fps. Minimize the deck, or move it to another workspace, and only the engine runs. `TAPEDECK_FPS=15` costs about 1–2 % more. In one 60 s sample, Xorg read 11–12 % before the window was restacked (minimized and restored), and 3–3.5 % in every sample after it. The cause wasn't found.

Earlier milestones (for comparison): UI 0.3–0.56 % playing without animation (0.3–0.4); librespot ~1.0 %; the window maps 0.7 s after launch.


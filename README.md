# tapedeck

Spotify client for HAVEN, in the style of a Win98 desktop utility with a cassette-deck display. Status: **deck + drawer + browsing + life work**: playlists, Liked Songs, search, the queue, artist and album pages, artist radio, album art on the display, spinning reels, real VU meters, MPRIS and media keys (packaging next). See [PLAN.md](PLAN.md).

## Setup
1. librespot: `cargo install librespot --version 0.8.0 --locked --no-default-features --features rustls-tls-native-roots`
2. Spotify developer app with redirect URI `http://127.0.0.1:8898/callback`, then `python3 -m tapedeck.cli setup <client_id>` and `python3 -m tapedeck.cli login`
3. Start the engine: `bin/tapedeck-engine` (first run opens the browser for librespot's own login)

## Run
`bin/tapedeck`, or **TAPEDECK** in the XFCE menu (`tapedeck.desktop` is copied to `~/.local/share/applications/`). It starts the librespot engine if it isn't already running and stops it again on exit.

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

## Measured (2026-10-13, playing 160 kbps)
| process | RSS | CPU |
|---|---|---|
| librespot | 22 MB | ~1.0 % |
| pacat | 5 MB | ~0.2 % |
| tapedeck UI, playing, visible | 71 MB | 0.35 % |
| tapedeck UI, playing, drawer open, 697 rows | 78 MB | 0.30 % |
| tapedeck UI 0.4, playing, J-card art, radio page open | 78 MB | 0.56 % |
| tapedeck UI 0.5, playing, visible, reels + VU at 10 fps | 78 MB | 4.0 % (+ Xorg 3.2 %, xfwm4 1.0 %, parec 0.1 %) |
| tapedeck UI 0.5, paused, or minimized | 78 MB | 0 % |
| librespot (same 30 s window, 0.5) | | 3.9 % |

The window maps 0.7 s after launch. UI RSS is just over the 70 MB target, mostly GTK at 2x HiDPI scale. With animation, the visible-and-playing total is ~8 % for the UI side. Most of it is GTK's per-frame overhead, not drawing (a frame draws in about 1 ms). At 15 fps it was ~9 %; drawing straight to the X window cost ~12 % at 15 fps. Minimize the deck, or move it to another workspace, and the cost drops to 0.

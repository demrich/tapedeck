# tapedeck

Spotify client for HAVEN, in the style of a Win98 desktop utility with a cassette-deck display. Status: **deck + drawer + browsing work**: playlists, Liked Songs, search, the queue, artist and album pages, artist radio and album art on the display (animations, VU meters and media keys next). See [PLAN.md](PLAN.md).

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
Press `A` or `B` on a track, or click the artist line or the J-card on the display, to open an artist or album page. An artist page lists Popular tracks, Albums, Singles & EPs and Fans Also Like. Pages join the Cassette list, and Back walks the history.

Spotify withholds top tracks, related artists, recommendations and radio (`spotify:station:`) from development-mode apps. TAPEDECK gets those from **Deezer's public API** (no key, no account) and matches each song back to Spotify by search. A match must agree on the artist and the title; a song Spotify doesn't have is dropped rather than replaced by a wrong one (typically 22–25 of 25 radio tracks match). Starting radio takes about 4 s. Started from the song in the deck, the song keeps playing and the station follows. The engine also runs with `--autoplay on`, so when a tape ends, Spotify keeps playing similar music.

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

The window maps 0.7 s after launch. UI RSS is just over the 70 MB target, mostly GTK at 2x HiDPI scale. Check again after milestone 4.

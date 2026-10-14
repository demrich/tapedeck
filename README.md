# tapedeck

Spotify client for HAVEN, in the style of a Win98 desktop utility with a cassette-deck display. Status: **deck window works** (playlists and search drawer next). See [PLAN.md](PLAN.md).

## Setup
1. librespot: `cargo install librespot --version 0.8.0 --locked --no-default-features --features rustls-tls-native-roots`
2. Spotify developer app with redirect URI `http://127.0.0.1:8898/callback`, then `python3 -m tapedeck.cli setup <client_id>` and `python3 -m tapedeck.cli login`
3. Start the engine: `bin/tapedeck-engine` (first run opens the browser for librespot's own login)

## Run
`bin/tapedeck`, or **TAPEDECK** in the XFCE menu (`tapedeck.desktop` is copied to `~/.local/share/applications/`). It starts the librespot engine if it isn't already running and stops it again on exit.

The LCD uses the VT323 pixel font from `~/haven/shared/fonts/` (installed into `~/.local/share/fonts/`).

## Keys
`Space` play/pause · `S` stop · `H`/`L` previous/next · `Shift+H`/`Shift+L` seek ±10 s · `+`/`-` volume · `E` eject · `?` keyboard card · `Ctrl+Q` exit

## Test commands
`python3 -m tapedeck.cli devices | search <q> | playlists | play [uri] | pause | next | previous | now`

## Measured (2026-10-13, playing 160 kbps)
| process | RSS | CPU |
|---|---|---|
| librespot | 22 MB | ~1.0 % |
| pacat | 5 MB | ~0.2 % |
| tapedeck UI, playing, visible | 71 MB | 0.35 % |

The window maps 0.7 s after launch. UI RSS is just over the 70 MB target, mostly GTK at 2x HiDPI scale. Check again after milestone 4.

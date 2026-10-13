# tapedeck

Spotify client for HAVEN, in the style of a Win98 desktop utility with a cassette-deck display. Status: **engine works, UI not started**. See [PLAN.md](PLAN.md).

## Setup
1. librespot: `cargo install librespot --version 0.8.0 --locked --no-default-features --features rustls-tls-native-roots`
2. Spotify developer app with redirect URI `http://127.0.0.1:8898/callback`, then `python3 -m tapedeck.cli setup <client_id>` and `python3 -m tapedeck.cli login`
3. Start the engine: `bin/tapedeck-engine` (first run opens the browser for librespot's own login)

## Test commands
`python3 -m tapedeck.cli devices | search <q> | playlists | play [uri] | pause | next | previous | now`

## Measured (2026-10-13, playing 160 kbps)
| process | RSS | CPU |
|---|---|---|
| librespot | 22 MB | ~1.0 % |
| pacat | 5 MB | ~0.2 % |

# TAPEDECK — plan

A Spotify client shaped like a cassette deck. Mood: **cassette futurism**. Form: fixed-size skinned hardware deck, with the library in a pull-out drawer.

```
┌─ TAPEDECK ─────────────── ▪ ✕ ┐
│  ◎━━━━━━━━━━━━━━━━━◎   TYPE II │   reels spin only while playing; the tape
│  [SIDE A] NIGHTCALL  ▶ 02:41   │   moves from the left reel to the right as the track plays
│  L ▮▮▮▮▮▮▯▯  R ▮▮▮▮▮▯▯▯        │   real VU meters (measured from audio output)
│ [⏮][⏪][▶][⏸][⏩][⏭]  [EJECT] │   EJECT = open the cassette drawer
├────────────────────────────────┤
│ ▶ 01 Nightcall .......... 4:18 │   drawer: playlists = cassettes with J-cards
│   02 Resonance .......... 3:32 │
└────────────────────────────────┘
```

## Architecture

```
 ┌──────────────┐  Web API (HTTPS, only on user action)   ┌──────────────┐
 │  tapedeck UI │ ──────────────────────────────────────► │ Spotify API  │
 │ Python+GTK3  │  search · playlists · play/pause/seek    └──────┬───────┘
 │ + cairo deck │                                                │ Connect
 └──────▲───────┘                                         ┌──────▼───────┐
        │ events (track change, play, pause) via --onevent │  librespot   │ decodes Ogg Vorbis
        └──────────────────────────────────────────────────│ (Rust, ~20MB)│──► PulseAudio
                                                           └──────────────┘        │
                  VU meters ◄── parec monitor, 8 kHz mono, only while visible+playing
```

- **librespot**: a headless Spotify Connect device named "TAPEDECK". It handles login and decoding (`--backend pulseaudio --bitrate 160`, 320 optional). It pushes events to tapedeck through an `--onevent` hook, so tapedeck never polls.
- **tapedeck UI**: one cairo `DrawingArea` for the deck plus a GTK list for the drawer, themed with GTK CSS. The playback position is counted forward locally and resynced on each librespot event.
- **Spotify Web API**: PKCE OAuth with a personal developer app (no client secret). Tokens go in `~/.config/haven/tapedeck/`. It's used for search, playlists, liked songs, the queue and playback control.
- **Cache**: `~/.cache/haven/tapedeck/` holds album art downscaled to 64 px and dithered to the deck palette, plus playlist metadata as JSON.

## Performance targets
| | target |
|---|---|
| UI RSS | < 70 MB |
| librespot RSS | < 30 MB |
| CPU idle (paused / hidden) | ≈ 0 % |
| CPU playing, window visible | < 8 % (reels at 15 fps, VU at 20 Hz) |
| CPU playing, minimized | < 3 % (librespot only) |

## Look
Putty `#d8cfc0` body, charcoal `#2b2b2b` tape window, amber `#ffb000` segmented LCD, orange `#ff6a13` REC/warning accents, chunky beveled transport keys. Pixel fonts: VT323 for the LCD and Silkscreen for labels. Flavor text: "REWINDING TAPE…", "INSERT CASSETTE", "HEAD CLEANING REQUIRED" (network error).

## Keys
`space` play/pause · `h`/`l` prev/next · `H`/`L` seek ±10 s · `+`/`-` volume · `e` eject (drawer) · `/` search · `?` manual

## Milestones
0. **Setup**: build librespot (`cargo install librespot`, a one-time ~30–40 min compile on this CPU) and create a Spotify developer app (client ID, redirect `http://127.0.0.1:8898/callback`).
1. **Engine**: librespot runs as the "TAPEDECK" device, plus a Python Web API client with PKCE and token refresh. Test from the command line: search → play → pause.
2. **Deck**: draw the static deck in cairo, wire up the transport and LCD counter, connect the event hook.
3. **Drawer**: playlists and liked songs as cassettes, search, the queue.
4. **Life**: spinning reels, real VU meters, dithered J-card art, MacBook media keys via MPRIS.
5. **Ship**: `.desktop` entry, librespot user service, measure against the budget and record the numbers in the README.

## Caveats
- Spotify Premium is required (librespot and Web API playback control both need it).
- librespot is unofficial. It is widely used, but technically outside Spotify's ToS.
- A developer app in development mode is limited to a few allowlisted users, which is fine for personal use.

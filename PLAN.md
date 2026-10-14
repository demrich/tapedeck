# TAPEDECK — plan

A Spotify client in the style of a 90s desktop utility (think Win98 CD Player / Media Player 6.4, with a cassette deck as the display). It **uses the system theme** (IndigoMagic + SE98 icons), so its chrome matches the rest of the desktop. Only the deck display is custom-drawn.

```
┌─ TAPEDECK - Nightcall ───────────────── _ □ X ┐   xfwm4 IndigoMagic frame
│ File  Tape  View  Help                         │   GTK menu bar (themed)
│ ┌────────────────────────────────────────────┐ │
│ │  ◎═════════════◎  [SIDE A]   ▶ 02:41/4:18  │ │   sunken black display, cairo:
│ │  NIGHTCALL - KAVINSKY          TYPE II     │ │   spinning reels, green LCD,
│ │  L ▮▮▮▮▮▮▯▯▯▯   R ▮▮▮▮▮▯▯▯▯▯               │ │   real VU meters
│ └────────────────────────────────────────────┘ │
│ [⏮][⏪][▶][⏸][⏹][⏩][⏭]  ──●──── vol  [⏏]   │   stock GTK buttons, SE98 icons
├────────────────────────────────────────────────┤
│ Cassette: Night Drive ▾                        │   drawer (GtkRevealer) opened by ⏏
│ #  Title                Artist          Time   │   GtkTreeView: yellow selection
│ 1  Nightcall            Kavinsky        4:18   │   comes from the theme
│ 2  Resonance            HOME            3:32   │
├────────────────────────────────────────────────┤
│ Ready             │ TAPEDECK device │ 160 kbps │   sunken status bar panels
└────────────────────────────────────────────────┘
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

- **librespot**: a headless Spotify Connect device named "TAPEDECK". It handles login and decoding (`--backend pipe | pacat` (no libpulse-dev needed), `--bitrate 160`, 320 optional). It pushes events to tapedeck through an `--onevent` hook, so tapedeck never polls.
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
- Window chrome, menus, buttons, list and status bar are **stock GTK and inherit IndigoMagic**. Icons come from SE98 by freedesktop name (`media-playback-start`, `media-eject`, …).
- The only custom-drawn widget is the deck display: a sunken 2 px bevel around a black display with green `#00FF00` LCD digits (VT323), dark-gray tape reels, and VU meters running green → yellow → red. The bevel colors are read from the GTK style context.
- Album art appears as a small square in the display, dithered to 16 colors (period-correct).
- Flavor: "REWINDING TAPE…", "INSERT CASSETTE", and on a network error, a Win98-style dialog: "TAPEDECK has encountered a problem: HEAD CLEANING REQUIRED".

## Keys
Menu accelerators (`Tape → &Play  Space`) plus: `space` play/pause · `h`/`l` prev/next · `H`/`L` seek ±10 s · `+`/`-` volume · `e` eject (drawer) · `/` search · `?` manual

## Milestones
0. ✅ **Setup** (2026-10-13): build librespot (`cargo install librespot`, a one-time ~30–40 min compile on this CPU) and create a Spotify developer app (client ID, redirect `http://127.0.0.1:8898/callback`).
1. ✅ **Engine** (2026-10-13): librespot runs as the "TAPEDECK" device, plus a Python Web API client with PKCE and token refresh. Test from the command line: search → play → pause.
2. ✅ **Deck** (2026-10-13): window with menu bar, transport row and status bar; draw the display in cairo; wire up the transport and LCD counter, connect the event hook. The tape packs on the reels already follow the track position (rotation comes in milestone 4).
3. ✅ **Drawer** (2026-10-13): the eject button opens a list of cassettes (Liked Songs, your own playlists, then followed playlists marked [sealed]), plus search (10 results per page, with a "more results" row) and Up Next (the queue). Enter plays the selected track in its context, `Q` queues it, and Play Tape starts the cassette from the top. Tracklists are cached on disk and refetched only when the playlist's snapshot_id changes (Liked Songs: when its total or newest track changes). Sealed cassettes record each track as it's heard. Web API calls run on two worker lanes so a big load never delays transport commands.
3½. ✅ **Browse** (2026-10-13): artist pages (popular, albums, singles & EPs, fans also like) and album pages, opened with `A`/`B`, by clicking the display, or from search (which now also shows artists and albums). Back history. Artist radio. Album art as a dithered J-card on the display. Top tracks, look-alikes and radio come from Deezer's public API and are matched to Spotify tracks (dev mode returns 403 for top tracks and related artists, and 404 for recommendations; station URIs are refused).
4. ✅ **Life** (2026-10-13): reels turn at tape speed (faster as a reel empties, backwards while loading). Real VU meters from parec on TAPEDECK's own stream, volume-compensated. MPRIS player plus XF86Audio* shortcuts for the MacBook media keys. Measured ~8 % UI-side CPU at 10 fps while visible and playing, 0 % when paused or hidden. The 15 fps / 20 Hz target was dropped to keep under budget.
5. **Ship**: `.desktop` entry, librespot user service, measure against the budget and record the numbers in the README.

## Caveats
- **Development-mode API limits (verified 2026-10-13):** playlist track lists can only be read for playlists the user **owns**. Followed playlists return 403, but they can still be *played* by context URI. Show them as "sealed cassettes" whose tracklist fills in from librespot `track_changed` events. Search returns at most 10 results per request.
- **Also blocked in development mode (verified 2026-10-13):** artist top tracks (403), related artists (403), recommendations (404), `spotify:station:` contexts ("Non supported context uri"), page sizes over 10 for artist albums, and artist genres/followers (the fields are gone). Deezer's public API fills those gaps.
- Spotify Premium is required (librespot and Web API playback control both need it).
- librespot is unofficial. It is widely used, but technically outside Spotify's ToS.
- A developer app in development mode is limited to a few allowlisted users, which is fine for personal use.

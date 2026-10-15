"""Maintainer tool: render the README screenshots into docs/ from hardcoded catalog data.

Nothing touches your Spotify account, the engine or a running TAPEDECK (only the cover is
downloaded, like any cover): it uses its own application id,
fills the widgets directly and draws the window into a PNG. Run it headless under GTK broadway:

    broadwayd :7 & GDK_BACKEND=broadway BROADWAY_DISPLAY=:7 python3 tools/screenshots.py; kill %1
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tapedeck import look  # noqa: E402

look.prepare()

import cairo  # noqa: E402
import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from tapedeck import art, deck  # noqa: E402
from tapedeck.drawer import album_item, album_kind, heading, length, nav_item  # noqa: E402

OUT = os.path.join(ROOT, "docs")

# Real catalog data (Spotify Web API, 2026-10-15), hardcoded so the shots are reproducible offline.
ARTIST = "Magdalena Bay"
ALBUM = "Imaginal Disk"
ALBUM_URI = "spotify:album:2Htq1sHgmdGffojIBM6Q1s"
COVER = "https://i.scdn.co/image/ab67616d00004851a3390485ba30a0a99feaa0dd"
TRACKS = [   # Imaginal Disk (2024): title, ms
    ("She Looked Like Me!", 193186), ("Killing Time", 233546), ("True Blue Interlude", 109226),
    ("Image", 212866), ("Death & Romance", 314733), ("Fear, Sex", 152053),
    ("Vampire in the Corner", 202440), ("Watching T.V.", 245413), ("Tunnel Vision", 305520),
    ("Love Is Everywhere", 194413), ("Feeling DiskInserted?", 58600), ("That's My Floor", 209800),
    ("Cry for Me", 307266), ("Angel on a Satellite", 243426), ("The Ballad of Matt & Mica", 240000),
]
NOW = 3      # Image
POPULAR = [("Killshot", "Killshot", 236363), ("Image", ALBUM, 212866), ("Death & Romance", ALBUM, 314733),
           ("Killing Time", ALBUM, 233546), ("Fear, Sex", ALBUM, 152053)]
ALBUMS = [   # name, type, tracks, release date
    ("Imaginal Disk", "album", 15, "2024-08-23"), ("mini mix vol. 3", "album", 7, "2023-04-13"),
    ("Mercurial World (Deluxe)", "album", 28, "2022-09-23"), ("Mercurial World", "album", 14, "2021-10-08"),
    ("mini mix vol. 2", "album", 7, "2020-11-20"), ("A Little Rhythm and a Wicked Feeling", "album", 8, "2020-03-13"),
    ("mini mix vol. 1", "album", 7, "2019-07-19"),
    ("This Is The World (I Made It For You) / Nice Day", "single", 2, "2025-11-14"),
    ("Unoriginal / Black-Eyed Susan Climb", "single", 2, "2025-10-31"),
    ("Human Happens / Paint Me A Picture", "single", 2, "2025-10-17"),
]
SIMILAR = ["Caroline Polachek", "AFTER", "Charli xcx", "Hemlocke Springs"]


def uri(title):
    return "spotify:track:" + "".join(c for c in title.lower() if c.isalnum())


def album_rows():
    return [[t, ARTIST, ALBUM, ms, uri(t)] for t, ms in TRACKS]


def stage(d):
    title, ms = TRACKS[NOW]
    t = d.tape
    t.name, t.artists, t.album, t.uri = title, ARTIST, ALBUM, uri(title)
    t.duration_ms, t.mode, t.volume = ms, "play", 70
    t.set_pos(83_000)
    t.angles = [0.6, 2.1]
    t.vu = (0.74, 0.63)
    t.art = art.surface(art.load(COVER))    # the real cover, through the app's own dither
    d.quiet = True
    d.vol.set_value(70)
    d.quiet = False
    d.set_online(True)


def combo(dr, page, label):
    dr.combo.handler_block_by_func(dr._on_combo)
    dr.combo.remove_all()
    for cid, text in [("liked", "Liked Songs"), ("search", "Search Results"), ("queue", "Up Next (queue)"),
                      (page, "» " + label)]:
        dr.combo.append(cid, text)
    dr.combo.set_active_id(page)
    dr.combo.handler_unblock_by_func(dr._on_combo)


def shoot(w, name):
    a = w.get_allocation()
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, a.width, a.height)
    w.draw(cairo.Context(surf))
    surf.write_to_png(os.path.join(OUT, name))
    print(name, a.width, "x", a.height)


def album_page(d):
    """As Drawer._load_album lays it out."""
    dr, rows = d.drawer, album_rows()
    combo(dr, "album:demo", ALBUM)
    items = [heading("ALBUM · 2024")] + [("track", r) for r in rows]
    items += [heading("BY"), nav_item("artist", ARTIST, "spotify:artist:1oPRcJUkloHaRLYx0olBLJ", ARTIST)]
    dr._fill_items(items)
    dr.mark_playing(d.tape.uri, d.tape.name, d.tape.artists)
    dr.tree.set_cursor(Gtk.TreePath(5), None, False)     # Death & Romance
    d.say(f"{ALBUM} (2024): {len(rows)} tracks, {length(rows)}")


def artist_page(d):
    """As Drawer._load_artist's build() lays it out."""
    dr = d.drawer
    combo(dr, "artist:demo", ARTIST)
    kinds = {"Album": [], "EP": [], "Single": [], "Compilation": []}
    for name, typ, n, date in ALBUMS:
        al = {"name": name, "album_type": typ, "total_tracks": n, "release_date": date,
              "artists": [{"name": ARTIST}], "uri": "spotify:album:" + uri(name)[14:]}
        kinds[album_kind(al)].append(album_item(al))
    popular = [("track", [t, ARTIST, al, ms, uri(t)]) for t, al, ms in POPULAR]
    items = [nav_item("radio", f"{ARTIST} Radio", ARTIST, f"{ARTIST} Radio")]
    for head, group in [("POPULAR", popular), ("ALBUMS", kinds["Album"]), ("SINGLES", kinds["Single"]),
                        ("FANS ALSO LIKE", [nav_item("artist", n, "dz:" + n, n) for n in SIMILAR])]:
        items += [heading(head, len(group) if head != "POPULAR" else None)] + group
    dr._fill_items(items)
    dr.mark_playing(d.tape.uri, d.tape.name, d.tape.artists)
    d.say(f"{ARTIST}: {len(kinds['Album'])} albums, {len(kinds['Single'])} singles")


class Shots(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="cc.haunts.haven.tapedeck.screenshots",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)

    def do_activate(self):
        os.makedirs(OUT, exist_ok=True)
        w = deck.Deck(self)
        stage(w)
        w.show_all()
        steps = [
            lambda: shoot(w, "deck.png"),
            lambda: (w.revealer.set_reveal_child(True), album_page(w)),
            lambda: w.drawer.tree.scroll_to_point(-1, 0),
            lambda: shoot(w, "tape.png"),
            lambda: artist_page(w),
            lambda: w.drawer.tree.scroll_to_point(-1, 0),
            lambda: shoot(w, "artist.png"),
            self.quit,
        ]

        def step():
            steps.pop(0)()
            return bool(steps)
        GLib.timeout_add(700, step)


if __name__ == "__main__":
    look.apply()
    Shots().run(None)

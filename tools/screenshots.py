"""Maintainer tool: render the README screenshots into docs/ with made-up sample data.

Nothing touches Spotify, the engine or a running TAPEDECK: it uses its own application id,
fills the widgets directly and draws the window into a PNG. Run it headless under GTK broadway:

    broadwayd :7 & GDK_BACKEND=broadway BROADWAY_DISPLAY=:7 python3 tools/screenshots.py; kill %1
"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tapedeck import look  # noqa: E402

look.prepare()

import cairo  # noqa: E402
import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from tapedeck import art, deck  # noqa: E402
from tapedeck.drawer import heading, nav_item  # noqa: E402

OUT = os.path.join(ROOT, "docs")
MIN = 60_000

TAPE = "Night Drive"
TRACKS = [   # title, artist, album, ms
    ("Neon Overpass", "The Midnight Carriers", "Coastline Static", 4 * MIN + 12_000),
    ("Chrome Lullaby", "Vera Sol", "Afterglow FM", 3 * MIN + 48_000),
    ("Polaroid Summer", "Kid Cassette", "Rewind & Play", 3 * MIN + 31_000),
    ("Signal Lost", "The Midnight Carriers", "Coastline Static", 5 * MIN + 2_000),
    ("Arcade Rain", "Pixel Harbor", "Insert Coin", 4 * MIN + 40_000),
    ("Highway 9 (Dub)", "Lowlight Motel", "Vacancy", 6 * MIN + 15_000),
    ("Satellite Heart", "Vera Sol", "Afterglow FM", 3 * MIN + 57_000),
    ("Dial Tone Romance", "June Analog", "Party Line", 3 * MIN + 22_000),
    ("Magnetic North", "Kid Cassette", "Rewind & Play", 4 * MIN + 5_000),
    ("Slow Fade to Blue", "Lowlight Motel", "Vacancy", 5 * MIN + 33_000),
    ("Tokyo by Payphone", "Pixel Harbor", "Insert Coin", 3 * MIN + 49_000),
    ("Last Exit Sunrise", "June Analog", "Party Line", 4 * MIN + 28_000),
]
NOW = 1   # Chrome Lullaby


def rows():
    return [[t, a, al, ms, f"spotify:track:demo{i}"] for i, (t, a, al, ms) in enumerate(TRACKS)]


def cover():
    """A synthwave sunset, put through the same 52 px web-safe dither as real covers."""
    s = art.SIZE
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, s, s)
    cr = cairo.Context(surf)
    sky = cairo.LinearGradient(0, 0, 0, s * 0.62)
    sky.add_color_stop_rgb(0, 0.10, 0.04, 0.18)
    sky.add_color_stop_rgb(1, 1.0, 0.44, 0.81)
    cr.set_source(sky)
    cr.paint()
    sun = cairo.LinearGradient(0, s * 0.18, 0, s * 0.62)
    sun.add_color_stop_rgb(0, 1.0, 0.9, 0.3)
    sun.add_color_stop_rgb(1, 1.0, 0.3, 0.5)
    cr.set_source(sun)
    cr.arc(s / 2, s * 0.62, s * 0.3, math.pi, 0)
    cr.fill()
    cr.set_source_rgb(0.10, 0.04, 0.18)
    for i, y in enumerate((0.40, 0.48, 0.55)):
        cr.rectangle(0, s * y, s, 1 + i)
        cr.fill()
    cr.rectangle(0, s * 0.62, s, s)
    cr.fill()
    cr.set_source_rgb(0.0, 0.8, 1.0)
    cr.set_line_width(1)
    for k in range(-6, 7):
        cr.move_to(s / 2 + k * 2, s * 0.62)
        cr.line_to(s / 2 + k * 14, s)
    for y in (0.66, 0.72, 0.81, 0.93):
        cr.move_to(0, s * y)
        cr.line_to(s, s * y)
    cr.stroke()
    pb = Gdk.pixbuf_get_from_surface(surf, 0, 0, s, s)
    return art.surface(art._dither(pb))


def stage(d, playing=True):
    title, artist, album, ms = TRACKS[NOW]
    t = d.tape
    t.name, t.artists, t.album, t.uri = title, artist, album, f"spotify:track:demo{NOW}"
    t.duration_ms, t.mode, t.volume = ms, "play" if playing else "pause", 70
    t.set_pos(83_000)
    t.angles = [0.6, 2.1]
    t.vu = (0.74, 0.63) if playing else None
    t.art = cover()
    d.quiet = True
    d.vol.set_value(70)
    d.quiet = False
    d.set_online(True)


def combo(dr, entries, active):
    dr.combo.handler_block_by_func(dr._on_combo)
    dr.combo.remove_all()
    for cid, label in entries:
        dr.combo.append(cid, label)
    dr.combo.set_active_id(active)
    dr.combo.handler_unblock_by_func(dr._on_combo)


def shoot(w, name):
    a = w.get_allocation()
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, a.width, a.height)
    w.draw(cairo.Context(surf))
    surf.write_to_png(os.path.join(OUT, name))
    print(name, a.width, "x", a.height)


def tape_open(d):
    dr = d.drawer
    combo(dr, [("liked", "Liked Songs"), ("search", "Search Results"), ("queue", "Up Next (queue)"),
               ("demo", TAPE)], "demo")
    dr._fill(rows())
    dr.mark_playing(d.tape.uri, d.tape.name, d.tape.artists)
    dr.tree.set_cursor(Gtk.TreePath(3), None, False)
    dr._summary(TAPE)


def artist_page(d):
    dr = d.drawer
    combo(dr, [("liked", "Liked Songs"), ("search", "Search Results"), ("queue", "Up Next (queue)"),
               ("artist:demo", "» Vera Sol"), ("demo", TAPE)], "artist:demo")
    pop = [r for r in rows() if r[1] == "Vera Sol"] + [
        ["Paper Moon Radio", "Vera Sol", "Afterglow FM", 4 * MIN + 1_000, "spotify:track:demoA"],
        ["Velvet Static", "Vera Sol", "Velvet Static", 3 * MIN + 36_000, "spotify:track:demoB"]]
    dr._fill_items(
        [heading("Popular", len(pop))] + [("track", r) for r in pop]
        + [heading("Albums", 2),
           ("album", "Afterglow FM (1988)", "Vera Sol", "", "spotify:album:a", "Afterglow FM\nAlbum · 1988"),
           ("album", "Moonlight Switchboard (1986)", "Vera Sol", "", "spotify:album:b", "Album · 1986"),
           heading("Singles", 1),
           ("album", "Velvet Static (1989)", "Vera Sol", "", "spotify:album:c", "Single · 1989"),
           heading("Fans Also Like", 3),
           nav_item("artist", "June Analog", "spotify:artist:a", "June Analog"),
           nav_item("artist", "Pixel Harbor", "spotify:artist:b", "Pixel Harbor"),
           nav_item("radio", "Vera Sol Radio", "radio:demo", "Start radio")])
    dr.mark_playing(d.tape.uri, d.tape.name, d.tape.artists)
    d.say("Ready")


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
            lambda: (w.revealer.set_reveal_child(True), tape_open(w)),
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

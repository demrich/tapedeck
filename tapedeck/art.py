"""Album art for the deck display: the 64 px Spotify cover, shrunk to 52 px and ordered-dithered
to the 216-colour web-safe palette (6 levels per channel), then shown at 2x with hard pixel edges.

Processed covers are cached as small PNGs in ~/.cache/haven/tapedeck/art/, so each album is
downloaded and dithered once (about 3 KB on disk).
"""
import hashlib
import os
import urllib.request

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib

DIR = os.path.expanduser("~/.cache/haven/tapedeck/art")
SIZE = 52
BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]   # 4x4 ordered-dither matrix


def pick(urls):
    """The smallest cover that is still at least 64 px (Spotify's 64 px variant id is 00004851)."""
    urls = [u for u in urls if u]
    small = [u for u in urls if "00004851" in u]
    return (small or urls[-1:] or [None])[0]


def _path(url):
    return os.path.join(DIR, hashlib.sha1(url.encode()).hexdigest()[:16] + ".png")


def _dither(pb):
    n, stride = pb.get_n_channels(), pb.get_rowstride()
    src = pb.get_pixels()
    out = bytearray(SIZE * SIZE * 3)
    o = 0
    for y in range(SIZE):
        row = y * stride
        for x in range(SIZE):
            t = (BAYER[(y & 3) * 4 + (x & 3)] + 0.5) / 16 - 0.5   # -0.5 .. 0.5 of one step
            p = row + x * n
            for c in range(3):
                level = round(src[p + c] / 51 + t)
                out[o] = 51 * (0 if level < 0 else 5 if level > 5 else level)
                o += 1
    return GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(out)), GdkPixbuf.Colorspace.RGB, False, 8,
                                           SIZE, SIZE, SIZE * 3)


def load(url):
    """Worker thread: the dithered cover as a GdkPixbuf (from the cache, or downloaded once)."""
    path = _path(url)
    if not os.path.exists(path):
        with urllib.request.urlopen(url, timeout=15) as r:
            loader = GdkPixbuf.PixbufLoader()
            loader.write(r.read())
            loader.close()
        pb = loader.get_pixbuf().scale_simple(SIZE, SIZE, GdkPixbuf.InterpType.BILINEAR)
        os.makedirs(DIR, exist_ok=True)
        _dither(pb).savev(path + ".tmp", "png", [], [])
        os.replace(path + ".tmp", path)
    return GdkPixbuf.Pixbuf.new_from_file(path)


def surface(pb):
    """GTK thread: a cairo surface for display.draw (which stays free of GTK imports)."""
    return Gdk.cairo_surface_create_from_pixbuf(pb, 1, None)

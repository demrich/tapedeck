"""The deck display: a black LCD panel with a cassette and a green readout, drawn in cairo.

Pure drawing code (no GTK widgets) so it can also be rendered offscreen for tests.
"""
import math
import time

import cairo

import gi
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo

LCD = (0.0, 1.0, 0.0)        # #00FF00 lit segment
LCD_MID = (0.0, 0.62, 0.0)   # secondary text
LCD_DIM = (0.0, 0.32, 0.0)   # outlines, tape pack
LCD_GHOST = (0.0, 0.11, 0.0) # unlit "88:88" segments
VU_YEL = (1.0, 1.0, 0.0)
VU_RED = (1.0, 0.0, 0.0)
VU_SEGS = 24
FONT = "VT323"

_fonts = {}


def _font(px):
    if px not in _fonts:
        d = Pango.FontDescription.from_string(FONT)
        d.set_absolute_size(px * Pango.SCALE)
        _fonts[px] = d
    return _fonts[px]


def _text(cr, x, y, s, px, rgb, width=None, align_right=False):
    """Draw text with its top-left at (x, y); returns the logical width in px."""
    lay = PangoCairo.create_layout(cr)
    lay.set_font_description(_font(px))
    lay.set_text(s, -1)
    if width:
        lay.set_width(int(width * Pango.SCALE))
        lay.set_ellipsize(Pango.EllipsizeMode.END)
    tw = lay.get_pixel_extents()[1].width
    if align_right:
        x -= tw
    cr.set_source_rgb(*rgb)
    cr.move_to(x, y)
    PangoCairo.show_layout(cr, lay)
    return tw


def mmss(ms):
    if ms is None:
        return "--:--"
    s = max(0, int(ms // 1000))
    return f"{s // 60:02d}:{s % 60:02d}" if s < 6000 else "99:59"


class Tape:
    """Everything the display shows. Updated from librespot events and Web API syncs."""

    def __init__(self):
        self.name = None
        self.artists = ""
        self.album = ""
        self.uri = None
        self.covers = []
        self.duration_ms = 0
        self.mode = "stop"       # play | pause | stop | load
        self._pos = 0
        self._pos_at = time.monotonic()
        self.volume = None       # 0..100
        self.art = None          # cairo surface of the dithered cover (art.py), or None
        self.angles = [0.0, 0.0] # reel rotation (radians), advanced by Deck.animate
        self.vu = None           # (left, right) levels 0..1 while the meters run, else None

    def set_pos(self, ms):
        self._pos = int(ms)
        self._pos_at = time.monotonic()

    def position(self):
        pos = self._pos
        if self.mode == "play":
            pos += (time.monotonic() - self._pos_at) * 1000
        return min(pos, self.duration_ms) if self.duration_ms else pos

    def progress(self):
        return self.position() / self.duration_ms if self.duration_ms else 0.0


def _shape(cr, mode, x, y, s):
    """Transport glyph drawn as geometry (the pixel font has no ▶ ■)."""
    cr.set_source_rgb(*LCD)
    if mode == "play":
        cr.move_to(x, y); cr.line_to(x + s, y + s / 2); cr.line_to(x, y + s); cr.close_path()
    elif mode == "pause":
        cr.rectangle(x, y, s * 0.35, s); cr.rectangle(x + s * 0.65, y, s * 0.35, s)
    elif mode == "load":
        for i in (0, 1):  # rewind: two left-pointing triangles
            o = x + i * s / 2
            cr.move_to(o + s / 2, y); cr.line_to(o, y + s / 2); cr.line_to(o + s / 2, y + s); cr.close_path()
    else:
        cr.rectangle(x, y, s, s)
    cr.fill()


def _reel(cr, cx, cy, pack_r, angle):
    cr.set_source_rgb(*LCD_DIM)
    cr.arc(cx, cy, pack_r, 0, 2 * math.pi)
    cr.fill()
    cr.set_source_rgb(0, 0, 0)
    cr.arc(cx, cy, 9, 0, 2 * math.pi)
    cr.fill()
    cr.set_source_rgb(*LCD)
    cr.set_line_width(1.5)
    cr.arc(cx, cy, 9, 0, 2 * math.pi)
    cr.stroke()
    for i in range(3):  # sprocket teeth
        a = angle + i * 2 * math.pi / 3
        cr.move_to(cx + 4 * math.cos(a), cy + 4 * math.sin(a))
        cr.line_to(cx + 9 * math.cos(a), cy + 9 * math.sin(a))
    cr.stroke()


def reel_radii(h, w, progress):
    """Pack radii (supply, take-up) for a cassette of this size; area-proportional to the tape left."""
    wh = h - 40
    rh, rmax = 10, min(wh / 2 - 2, (w - 40) / 4)
    return (math.sqrt(rh * rh + (rmax * rmax - rh * rh) * (1 - progress)),
            math.sqrt(rh * rh + (rmax * rmax - rh * rh) * progress))


def _cassette(cr, x, y, w, h, progress, angles, label):
    cr.set_line_width(1)
    cr.set_source_rgb(*LCD_DIM)
    cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)  # shell
    cr.stroke()
    if label:
        _text(cr, x + 6, y + 2, label, 16, LCD_MID, width=w - 12)
    # window with the two packs: area-proportional radii, supply (left) empties as the track plays
    wy, wh = y + 22, h - 40
    cr.rectangle(x + 14.5, wy + 0.5, w - 29, wh)
    cr.stroke()
    cy = wy + wh / 2
    lx, rx = x + w * 0.3, x + w * 0.7
    rl, rr = reel_radii(h, w, progress)
    _reel(cr, lx, cy, rl, angles[0])
    _reel(cr, rx, cy, rr, angles[1])
    # head opening at the bottom edge
    by = y + h - 12
    cr.set_source_rgb(*LCD_DIM)
    cr.set_line_width(1)
    cr.move_to(x + 28.5, y + h - 0.5); cr.line_to(x + 36.5, by + 0.5)
    cr.line_to(x + w - 36.5, by + 0.5); cr.line_to(x + w - 28.5, y + h - 0.5)
    cr.stroke()
    # tape path: off each pack, down past the head
    cr.set_source_rgb(*LCD_MID)
    cr.move_to(lx - rl, cy); cr.line_to(x + 22, by + 6); cr.line_to(x + w - 22, by + 6); cr.line_to(rx + rr, cy)
    cr.stroke()


def _jcard(cr, x, y, s, surf):
    """The cover in a dim frame, each dithered pixel drawn as a hard-edged 2x2 block."""
    cr.set_line_width(1)
    cr.set_source_rgb(*LCD_DIM)
    cr.rectangle(x + 0.5, y + 0.5, s - 1, s - 1)
    cr.stroke()
    if surf is None:
        _text(cr, x + s / 2 - 22, y + s / 2 - 18, "NO", 18, LCD_GHOST)
        _text(cr, x + s / 2 - 22, y + s / 2 - 2, "J-CARD", 18, LCD_GHOST)
        return
    inner = s - 4
    cr.save()
    cr.translate(x + 2, y + 2)
    cr.scale(inner / surf.get_width(), inner / surf.get_height())
    cr.set_source_surface(surf, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_NEAREST)
    cr.paint()
    cr.restore()


CASSETTE = (8, 8, 150)   # x, y, width; height is the display height - 16
JCARD = 108              # 52 px cover at exactly 2x, plus a 2 px frame


def regions(w, h):
    """Rectangles redrawn by the animation timer: the cassette window (reels) and the meter bars."""
    x, y, cw = CASSETTE
    x0, right = 170, w - JCARD - 18
    return [(x + 14, y + 22, cw - 28, h - 16 - 40 + 2), (x0 + 12, h - 31, right - x0 - 12, 15)]


VU_ZONES = ((0, round(VU_SEGS * 0.7), LCD), (round(VU_SEGS * 0.7), round(VU_SEGS * 0.88), VU_YEL),
            (round(VU_SEGS * 0.88), VU_SEGS, VU_RED))


def _vu(cr, x, y, w, level, label):
    """One meter: L/R label and VU_SEGS segments, green to yellow to red, unlit ones ghosted.
    One fill per colour: this runs every animation frame."""
    if label:
        _text(cr, x, y - 6, label, 16, LCD_MID)
    x += 12
    seg = (w - 12) / VU_SEGS
    lit = round(level * VU_SEGS)
    for a, b, rgb in VU_ZONES + ((lit, VU_SEGS, LCD_GHOST),):
        if rgb is not LCD_GHOST:
            b = min(b, lit)
        for i in range(a, b):
            cr.rectangle(round(x + i * seg), y, max(1, round(seg) - 2), 5)
        cr.set_source_rgb(*rgb)
        cr.fill()


def draw(cr, w, h, tape, bitrate="160"):
    cr.set_source_rgb(0, 0, 0)
    cr.paint()

    x0 = 170
    right = w - JCARD - 18
    tw = right - x0
    # animation frames clip to regions(): then only the reels and meter bars are worth drawing
    full = cr.in_clip(x0 + 4, 40)

    cx, cy, cw_ = CASSETTE
    _cassette(cr, cx, cy, cw_, h - 16, tape.progress(), tape.angles, full and "SIDE A  C-90")
    vl, vr = tape.vu or (0, 0)    # live levels while playing, ghost segments otherwise
    _vu(cr, x0, h - 31, tw, vl, full and "L")
    _vu(cr, x0, h - 21, tw, vr, full and "R")
    if not full:
        return
    _jcard(cr, w - 8 - JCARD, (h - JCARD) // 2, JCARD, tape.art)

    word = {"play": "PLAY", "pause": "PAUSE", "stop": "STOP", "load": "REWINDING TAPE..."}[tape.mode]
    _shape(cr, tape.mode, x0, 10, 12)
    _text(cr, x0 + (28 if tape.mode == "load" else 18), 4, word, 20, LCD)
    if tape.mode != "load":   # the long REWINDING word needs the whole row
        _text(cr, right, 4, f"TYPE II {bitrate}K", 20, LCD_MID, align_right=True)

    # counter with unlit ghost segments behind it
    if tape.name:
        _text(cr, x0 - 2, 18, "88:88", 52, LCD_GHOST)
    cw = _text(cr, x0 - 2, 18, mmss(tape.position() if tape.name else None), 52, LCD)
    _text(cr, x0 + cw + 6, 40, "/ " + mmss(tape.duration_ms if tape.name else None), 24, LCD_MID)

    if tape.name:
        _text(cr, x0, 62, tape.name.upper(), 24, LCD, width=tw)
        sub = " / ".join(s for s in (tape.artists, tape.album) if s)
        _text(cr, x0, 82, sub.upper(), 18, LCD_MID, width=tw)
    else:
        _text(cr, x0, 62, "INSERT CASSETTE", 24, LCD, width=tw)
        _text(cr, x0, 82, "PRESS PLAY OR EJECT [E]", 18, LCD_MID, width=tw)

    # tape counter bar
    by = h - 10
    cr.set_line_width(1)
    cr.set_source_rgb(*LCD_DIM)
    cr.rectangle(x0 + 0.5, by + 0.5, tw - 1, 5)
    cr.stroke()
    cr.set_source_rgb(*LCD)
    cr.rectangle(x0 + 2, by + 2, (tw - 4) * (tape.progress() if tape.name else 0), 2)
    cr.fill()

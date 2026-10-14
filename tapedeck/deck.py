"""TAPEDECK main window: stock GTK chrome (inherits the system theme) around the cairo deck display.

Event-driven: librespot appends player events to $XDG_RUNTIME_DIR/tapedeck/events, which is
watched with inotify (GFileMonitor). The Web API is only called on user actions, from one
worker thread, so the UI thread never blocks on the network.
"""
import os
import queue
import signal
import subprocess
import threading
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from . import display, spotify

VERSION = "0.2"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, "bin", "tapedeck-engine")
RUN_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "tapedeck")
EVENTS = os.path.join(RUN_DIR, "events")
BITRATE = os.environ.get("TAPEDECK_BITRATE", "160")
DEVICE = "TAPEDECK"
SEEK_MS = 10_000

KEYS = [
    ("Space", "Play / Pause"),
    ("S", "Stop (pause and rewind to start)"),
    ("H / L", "Previous / next track"),
    ("Shift+H / Shift+L", "Rewind / fast-forward 10 s"),
    ("+ / -", "Volume up / down"),
    ("E", "Eject (open the drawer)"),
    ("?", "This card"),
    ("Ctrl+Q", "Exit"),
]


def engine_running():
    return subprocess.run(["pgrep", "-f", f"librespot --name {DEVICE}"],
                          stdout=subprocess.DEVNULL).returncode == 0


def parse_event(line):
    ev = {}
    for part in line.rstrip("\n").split("\t"):
        k, _, v = part.partition("=")
        ev[k] = v
    return ev


class Deck(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="TAPEDECK")
        self.set_icon_name("multimedia-player")
        self.set_resizable(False)
        self.tape = display.Tape()
        self.sp = None
        self.device_id = None
        self.engine = None          # Popen if we started librespot ourselves
        self.online = False
        self.ev_offset = 0
        self.tick_id = 0
        self.vol_id = 0
        self.quiet = False          # set while syncing widgets from events (no feedback loop)
        self.hidden = False
        self.jobs = queue.Queue()

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(box)
        box.pack_start(self._menubar(), False, False, 0)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, border_width=6)
        box.pack_start(body, True, True, 0)

        frame = Gtk.Frame(shadow_type=Gtk.ShadowType.IN)   # theme draws the sunken bevel
        self.lcd = Gtk.DrawingArea()
        self.lcd.set_size_request(480, 120)
        self.lcd.connect("draw", lambda a, cr: display.draw(
            cr, a.get_allocated_width(), a.get_allocated_height(), self.tape, bitrate=BITRATE))
        frame.add(self.lcd)
        body.pack_start(frame, False, False, 0)
        body.pack_start(self._transport(), False, False, 0)

        box.pack_end(self._statusbar(), False, False, 0)

        self.connect("key-press-event", self._on_key)
        self.connect("window-state-event", self._on_window_state)
        self.connect("delete-event", lambda *a: self.quit() or True)

    # --- widgets -----------------------------------------------------------
    def _menubar(self):
        accel = Gtk.AccelGroup()
        self.add_accel_group(accel)
        bar = Gtk.MenuBar()

        def menu(title, items):
            top = Gtk.MenuItem.new_with_mnemonic(title)
            sub = Gtk.Menu()
            top.set_submenu(sub)
            for it in items:
                if it is None:
                    sub.append(Gtk.SeparatorMenuItem())
                    continue
                label, cb, key = it[:3]
                if len(it) > 3 and it[3] == "check":
                    mi = Gtk.CheckMenuItem.new_with_mnemonic(label)
                    mi.connect("toggled", cb)
                else:
                    mi = Gtk.MenuItem.new_with_mnemonic(label)
                    mi.connect("activate", lambda _w, f=cb: f())
                if key:
                    kv, mods = Gtk.accelerator_parse(key)
                    if mods & Gdk.ModifierType.CONTROL_MASK:
                        mi.add_accelerator("activate", accel, kv, mods, Gtk.AccelFlags.VISIBLE)
                    else:  # bare keys are handled in _on_key (so they never eat typing); just show them
                        mi.get_child().set_accel(kv, mods)
                sub.append(mi)
            bar.append(top)
            return sub

        menu("_File", [
            ("_Sign In to Spotify...", self.sign_in, None),
            None,
            ("E_xit", self.quit, "<Control>q"),
        ])
        menu("_Tape", [
            ("_Play / Pause", self.play_pause, "space"),
            ("_Stop", self.stop, "s"),
            None,
            ("P_revious Track", self.previous, "h"),
            ("_Next Track", self.next, "l"),
            ("Re_wind 10 s", lambda: self.seek_by(-SEEK_MS), "<Shift>h"),
            ("_Fast Forward 10 s", lambda: self.seek_by(SEEK_MS), "<Shift>l"),
            None,
            ("_Eject", self.eject, "e"),
        ])
        menu("_View", [
            ("Always on _Top", lambda w: self.set_keep_above(w.get_active()), None, "check"),
        ])
        menu("_Help", [
            ("_Keyboard Card", self.show_keys, "question"),
            None,
            ("_About TAPEDECK", self.show_about, None),
        ])
        return bar

    def _button(self, icon, tip, cb):
        b = Gtk.Button()
        b.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR))
        b.set_tooltip_text(tip)
        b.set_can_focus(False)       # keyboard goes to the deck, not to button focus rings
        b.connect("clicked", lambda _b: cb())
        return b

    def _transport(self):
        row = Gtk.Box(spacing=2)
        for icon, tip, cb in [
            ("media-skip-backward", "Previous track (H)", self.previous),
            ("media-seek-backward", "Rewind 10 s (Shift+H)", lambda: self.seek_by(-SEEK_MS)),
            ("media-playback-start", "Play (Space)", self.play),
            ("media-playback-pause", "Pause (Space)", self.pause),
            ("media-playback-stop", "Stop (S)", self.stop),
            ("media-seek-forward", "Fast forward 10 s (Shift+L)", lambda: self.seek_by(SEEK_MS)),
            ("media-skip-forward", "Next track (L)", self.next),
        ]:
            row.pack_start(self._button(icon, tip, cb), False, False, 0)

        self.eject_btn = self._button("media-eject", "Eject: open the drawer (E)", self.eject)
        self.eject_btn.set_sensitive(False)   # the drawer arrives in milestone 3
        row.pack_end(self.eject_btn, False, False, 0)

        self.vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.vol.set_draw_value(False)
        self.vol.set_size_request(110, -1)
        self.vol.set_can_focus(False)
        self.vol.set_tooltip_text("Volume (+ / -)")
        self.vol.connect("value-changed", self._on_volume)
        row.pack_end(self.vol, False, False, 6)
        row.pack_end(Gtk.Image.new_from_icon_name("audio-volume-high", Gtk.IconSize.SMALL_TOOLBAR), False, False, 0)
        return row

    def _statusbar(self):
        row = Gtk.Box(spacing=2, border_width=2)

        def panel(text, expand):
            f = Gtk.Frame(shadow_type=Gtk.ShadowType.IN)
            lab = Gtk.Label(label=text, xalign=0, margin_start=4, margin_end=4)
            lab.set_ellipsize(Pango.EllipsizeMode.END if expand else Pango.EllipsizeMode.NONE)
            f.add(lab)
            row.pack_start(f, expand, expand, 0)
            return lab

        self.st_msg = panel("Ready", True)
        self.st_dev = panel(f"{DEVICE}: offline", False)
        panel(f"{BITRATE} kbps", False)
        return row

    # --- status ------------------------------------------------------------
    def say(self, text):
        self.st_msg.set_text(text)

    def set_online(self, online):
        self.online = online
        self.st_dev.set_text(f"{DEVICE}: {'online' if online else 'offline'}")

    def refresh(self):
        t = self.tape
        self.set_title(f"TAPEDECK - {t.name}" if t.name else "TAPEDECK")
        self.lcd.queue_draw()
        self._schedule_tick()

    # The counter only changes once a second, so wake exactly at the next second boundary
    # while playing and visible; otherwise no timer at all.
    def _schedule_tick(self):
        if self.tick_id:
            GLib.source_remove(self.tick_id)
            self.tick_id = 0
        if self.tape.mode == "play" and not self.hidden:
            delay = 1000 - int(self.tape.position()) % 1000 + 5
            self.tick_id = GLib.timeout_add(delay, self._tick)

    def _tick(self):
        self.tick_id = 0
        self.lcd.queue_draw()
        self._schedule_tick()
        return False

    def _on_window_state(self, _w, ev):
        self.hidden = bool(ev.new_window_state & Gdk.WindowState.ICONIFIED)
        self.refresh()

    # --- engine + events ---------------------------------------------------
    def boot(self):
        os.makedirs(RUN_DIR, exist_ok=True)
        if not os.path.exists(EVENTS):
            open(EVENTS, "a").close()
        if engine_running():
            self.read_events(replay=True)
        else:
            self.say("WARMING UP THE HEADS...")
            self.ev_offset = os.path.getsize(EVENTS)   # the engine truncates the file on start
            log = open(os.path.join(RUN_DIR, "engine.log"), "ab")
            self.engine = subprocess.Popen([ENGINE], stdout=log, stderr=log, start_new_session=True)
        self.monitor = Gio.File.new_for_path(EVENTS).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", lambda *a: self.read_events())

        threading.Thread(target=self._worker, daemon=True).start()
        try:
            self.sp = spotify.Spotify()
        except (OSError, ValueError):
            self.say("INSERT CASSETTE: File > Sign In to Spotify")
            return False
        self.api(self.sp.state, done=self._synced)
        return False

    def read_events(self, replay=False):
        try:
            with open(EVENTS) as f:
                f.seek(0, os.SEEK_END)
                if f.tell() < self.ev_offset:   # engine restarted and truncated the file
                    self.ev_offset = 0
                f.seek(self.ev_offset)
                data = f.read()
        except OSError:
            return
        data = data[:data.rfind("\n") + 1]   # only complete lines; a partial one is re-read next time
        self.ev_offset += len(data.encode())
        for line in data.splitlines():
            if line.startswith("event="):
                self.apply(parse_event(line), replay)
        self.refresh()

    def apply(self, ev, replay=False):
        t, name = self.tape, ev.get("event")
        if name == "track_changed":
            t.name = ev.get("NAME")
            t.artists = ev.get("ARTISTS", "").replace(" | ", ", ")
            t.album = ev.get("ALBUM", "")
            t.uri = ev.get("URI")
            t.covers = ev.get("COVERS", "").split(" | ")
            t.duration_ms = int(ev.get("DURATION_MS") or 0)
        elif name in ("playing", "paused", "seeked", "position_correction"):
            if name != "seeked" and name != "position_correction":
                t.mode = "play" if name == "playing" else "pause"
            t.set_pos(ev.get("POSITION_MS") or 0)
            if not replay:
                self.say("Playing" if t.mode == "play" else "Paused")
        elif name == "loading":
            t.mode = "load"
            t.set_pos(ev.get("POSITION_MS") or 0)
        elif name in ("stopped", "end_of_track"):
            if name == "stopped":
                t.mode = "stop"
        elif name == "volume_changed" and ev.get("VOLUME"):
            t.volume = round(int(ev["VOLUME"]) * 100 / 65535)
            self.quiet = True
            self.vol.set_value(t.volume)
            self.quiet = False
        elif name == "session_connected":
            self.set_online(True)
            if not replay:
                self.say("Ready")
        elif name == "session_disconnected":
            self.set_online(False)
        elif name == "unavailable" and not replay:
            self.say("TRACK UNAVAILABLE: skipping")

    # --- Web API worker ----------------------------------------------------
    def api(self, fn, *args, done=None):
        self.jobs.put((fn, args, done))

    def _worker(self):
        while True:
            fn, args, done = self.jobs.get()
            try:
                res, err = fn(*args), None
            except Exception as e:  # network or API error; reported in the status bar
                res, err = None, e
            GLib.idle_add(self._job_done, done, res, err)

    def _job_done(self, done, res, err):
        if err is None:
            if done:
                done(res)
        elif isinstance(err, spotify.SpotifyError) and err.status == 404:
            self.say("NO TAPE IN DECK: press Play to take over playback")
        else:
            self.say(f"HEAD CLEANING REQUIRED: {err}")
        return False

    def _device(self):
        """Worker thread: find the TAPEDECK device id (it appears a few seconds after librespot starts)."""
        for _ in range(10):
            if self.device_id:
                return self.device_id
            self.device_id = self.sp.device_id(DEVICE)
            if not self.device_id:
                time.sleep(1)
        raise RuntimeError("the TAPEDECK engine is not online; see engine.log")

    def _synced(self, st):
        dev = (st or {}).get("device") or {}
        if not st or dev.get("name") != DEVICE:
            if dev.get("name"):
                self.say(f"Spotify is playing on {dev['name']}: press Play to take over")
            return
        item = st.get("item") or {}
        t = self.tape
        t.name = item.get("name") or t.name
        t.artists = ", ".join(a["name"] for a in item.get("artists", [])) or t.artists
        t.album = (item.get("album") or {}).get("name", t.album)
        t.duration_ms = item.get("duration_ms") or t.duration_ms
        t.mode = "play" if st.get("is_playing") else "pause"
        t.set_pos(st.get("progress_ms") or 0)
        if dev.get("volume_percent") is not None:
            self.quiet = True
            self.vol.set_value(dev["volume_percent"])
            self.quiet = False
        self.set_online(True)
        self.refresh()

    # --- actions -----------------------------------------------------------
    def _need_login(self):
        if self.sp is None:
            self.say("INSERT CASSETTE: File > Sign In to Spotify")
            return True
        return False

    def play(self):
        if self._need_login():
            return
        self.say("REWINDING TAPE...")
        self.api(lambda: self.sp.play(self._device()))

    def pause(self):
        if not self._need_login():
            self.api(self.sp.pause)

    def play_pause(self):
        (self.pause if self.tape.mode == "play" else self.play)()

    def stop(self):
        if self._need_login():
            return
        def job():
            if self.tape.mode == "play":
                self.sp.pause()
            self.sp.seek(0)
        self.api(job, done=lambda _r: self.say("Stopped"))

    def next(self):
        if not self._need_login():
            self.api(self.sp.next)

    def previous(self):
        if not self._need_login():
            self.api(self.sp.previous)

    def seek_by(self, delta):
        if self._need_login() or not self.tape.name:
            return
        pos = max(0, min(self.tape.position() + delta, self.tape.duration_ms - 1000))
        self.tape.set_pos(pos)   # move the counter now; librespot confirms with "seeked"
        self.refresh()
        self.api(self.sp.seek, pos)

    def _on_volume(self, scale):
        if self.quiet or self.sp is None:
            return
        if self.vol_id:
            GLib.source_remove(self.vol_id)
        def send():   # debounce: one request after the slider settles
            self.vol_id = 0
            self.api(self.sp.volume, int(scale.get_value()))
            return False
        self.vol_id = GLib.timeout_add(250, send)

    def nudge_volume(self, d):
        self.vol.set_value(max(0, min(100, self.vol.get_value() + d)))

    def eject(self):
        self.say("The drawer is still being built (milestone 3)")

    def sign_in(self):
        self.say("Waiting for Spotify in your browser...")
        def done(_tok):
            self.sp = spotify.Spotify()
            self.say("Cassette loaded: signed in")
            self.api(self.sp.state, done=self._synced)
        self.api(spotify.login, done=done)

    def show_keys(self):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.INFO,
                              buttons=Gtk.ButtonsType.OK, text="TAPEDECK Keyboard Card")
        d.format_secondary_text("\n".join(f"{k:<20} {v}" for k, v in KEYS))
        d.run()
        d.destroy()

    def show_about(self):
        d = Gtk.AboutDialog(transient_for=self, modal=True)
        d.set_program_name("TAPEDECK")
        d.set_version(VERSION)
        d.set_logo_icon_name("multimedia-player")
        d.set_comments("A Spotify cassette deck for small old machines.\n"
                       "Part of HAVEN. Audio by librespot.\n\n"
                       "Be kind, rewind.")
        d.set_copyright("(c) 2026 demrich")
        d.run()
        d.destroy()

    def _on_key(self, _w, ev):
        if ev.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK):
            return False
        if isinstance(self.get_focus(), Gtk.Entry):
            return False
        k = Gdk.keyval_name(ev.keyval)
        action = {
            "space": self.play_pause,
            "s": self.stop,
            "h": self.previous,
            "l": self.next,
            "H": lambda: self.seek_by(-SEEK_MS),
            "L": lambda: self.seek_by(SEEK_MS),
            "plus": lambda: self.nudge_volume(5), "equal": lambda: self.nudge_volume(5),
            "KP_Add": lambda: self.nudge_volume(5),
            "minus": lambda: self.nudge_volume(-5), "KP_Subtract": lambda: self.nudge_volume(-5),
            "e": self.eject,
            "question": self.show_keys,
        }.get(k)
        if action:
            action()
            return True
        return False

    def quit(self):
        if self.engine and self.engine.poll() is None:
            try:
                os.killpg(self.engine.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        self.get_application().quit()


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="cc.haunts.haven.tapedeck",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win = None

    def do_activate(self):
        if self.win:            # single instance: a second launch just raises the deck
            self.win.present()
            return
        self.win = Deck(self)
        self.win.show_all()
        GLib.idle_add(self.win.boot)   # first paint before any process spawns or file reads


def main():
    GLib.set_prgname("tapedeck")
    Gdk.set_program_class("Tapedeck")
    GLib.set_application_name("TAPEDECK")
    return App().run(None)

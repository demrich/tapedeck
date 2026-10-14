"""VU meters: peak levels of TAPEDECK's own audio stream, not whatever else the machine is playing.

parec records the monitor of the TAPEDECK sink input (pacat's stream) at 8 kHz, which is plenty
for a meter. It runs only while the deck plays in a visible window. Chunks arrive about 20 times a
second on a GLib IO watch, so no thread and no polling.
"""
import json
import math
import os
import subprocess
from array import array

from gi.repository import GLib

RATE = 8000
FLOOR_DB = -36.0          # the leftmost segment; quieter than this reads as silence
FALL_PER_S = 1.6          # needle ballistics: rise at once, fall over about 0.6 s
SOFTVOL_DB = 60.0         # librespot's log volume range (engine default: --volume-range 60)


def stream_index(name="TAPEDECK"):
    """PulseAudio index of the engine's playback stream (it changes when the engine restarts)."""
    out = subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"],
                         capture_output=True, text=True, timeout=3).stdout
    for si in json.loads(out or "[]"):
        if si.get("properties", {}).get("application.name") == name:
            return si["index"]
    return None


def _level(peak, gain_db):
    if peak <= 0:
        return 0.0
    db = 20 * math.log10(peak / 32768) + gain_db
    return max(0.0, min(1.0, 1 - db / FLOOR_DB))


class Meter:
    def __init__(self):
        self.proc = None
        self.watch = 0
        self.peak = [0.0, 0.0]   # newest chunk's levels, waiting to be shown
        self.shown = [0.0, 0.0]
        self.gain_db = 0.0

    def set_volume(self, percent):
        """Meters read the level on the tape, like a real deck: undo librespot's volume attenuation."""
        self.gain_db = SOFTVOL_DB * (1 - percent / 100) if percent else 0.0

    @property
    def running(self):
        return self.proc is not None

    def start(self):
        if self.proc:
            return True
        try:
            idx = stream_index()
        except (OSError, ValueError, subprocess.SubprocessError):
            idx = None
        if idx is None:
            return False
        self.proc = subprocess.Popen(
            ["parec", f"--monitor-stream={idx}", "--raw", "--format=s16le", f"--rate={RATE}",
             "--channels=2", "--latency-msec=50", "--client-name=TAPEDECK VU"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        os.set_blocking(self.proc.stdout.fileno(), False)
        self.watch = GLib.io_add_watch(self.proc.stdout.fileno(), GLib.PRIORITY_DEFAULT,
                                       GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self._read)
        return True

    def stop(self):
        if self.watch:
            GLib.source_remove(self.watch)
            self.watch = 0
        if self.proc:
            self.proc.terminate()
            self.proc.wait()
            self.proc.stdout.close()
            self.proc = None
        self.peak = [0.0, 0.0]
        self.shown = [0.0, 0.0]

    def _read(self, fd, cond):
        try:
            data = os.read(fd, 65536)
        except BlockingIOError:
            return True
        if not data or cond & (GLib.IO_HUP | GLib.IO_ERR):
            self.watch = 0
            self.stop()          # stream gone (engine restarted); start() finds the new one
            return False
        data = data[:len(data) & ~3]   # whole stereo frames
        a = array("h", data)
        for ch in (0, 1):
            s = a[ch::2]
            if s:
                self.peak[ch] = max(self.peak[ch], _level(max(max(s), -min(s)), self.gain_db))
        return True

    def levels(self, dt):
        """Animation frame: the meter readings after dt seconds of fall."""
        for ch in (0, 1):
            self.shown[ch] = max(self.peak[ch], self.shown[ch] - FALL_PER_S * dt)
            self.peak[ch] = 0.0
        return tuple(self.shown)

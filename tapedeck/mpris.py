"""MPRIS: the deck as org.mpris.MediaPlayer2.tapedeck, so media keys, Bluetooth headphone buttons
(through mpris-proxy) and any MPRIS applet can drive it and see what is playing.

Plain Gio D-Bus; no extra libraries. The deck calls changed() after each event it applies.
"""
from gi.repository import Gio, GLib

NAME = "org.mpris.MediaPlayer2.tapedeck"
PATH = "/org/mpris/MediaPlayer2"
ROOT = "org.mpris.MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"

XML = f"""<node>
 <interface name="{ROOT}">
  <method name="Raise"/><method name="Quit"/>
  <property name="CanQuit" type="b" access="read"/>
  <property name="CanRaise" type="b" access="read"/>
  <property name="HasTrackList" type="b" access="read"/>
  <property name="Identity" type="s" access="read"/>
  <property name="DesktopEntry" type="s" access="read"/>
  <property name="SupportedUriSchemes" type="as" access="read"/>
  <property name="SupportedMimeTypes" type="as" access="read"/>
 </interface>
 <interface name="{PLAYER}">
  <method name="Next"/><method name="Previous"/><method name="Pause"/><method name="PlayPause"/>
  <method name="Stop"/><method name="Play"/>
  <method name="Seek"><arg direction="in" name="Offset" type="x"/></method>
  <method name="SetPosition"><arg direction="in" name="TrackId" type="o"/>
   <arg direction="in" name="Position" type="x"/></method>
  <method name="OpenUri"><arg direction="in" name="Uri" type="s"/></method>
  <signal name="Seeked"><arg name="Position" type="x"/></signal>
  <property name="PlaybackStatus" type="s" access="read"/>
  <property name="Rate" type="d" access="readwrite"/>
  <property name="Metadata" type="a{{sv}}" access="read"/>
  <property name="Volume" type="d" access="readwrite"/>
  <property name="Position" type="x" access="read"/>
  <property name="MinimumRate" type="d" access="read"/>
  <property name="MaximumRate" type="d" access="read"/>
  <property name="CanGoNext" type="b" access="read"/>
  <property name="CanGoPrevious" type="b" access="read"/>
  <property name="CanPlay" type="b" access="read"/>
  <property name="CanPause" type="b" access="read"/>
  <property name="CanSeek" type="b" access="read"/>
  <property name="CanControl" type="b" access="read"/>
 </interface>
</node>"""

STATUS = {"play": "Playing", "pause": "Paused", "load": "Playing", "stop": "Stopped"}


def _track_path(uri):
    """Spotify URI as a D-Bus object path (MPRIS wants a path for the track id)."""
    if not uri:
        return "/org/mpris/MediaPlayer2/TrackList/NoTrack"
    return "/cc/haunts/haven/tapedeck/track/" + uri.split(":")[-1]


class Mpris:
    def __init__(self, deck, conn):
        self.deck, self.conn = deck, conn
        self.sent = {}
        info = Gio.DBusNodeInfo.new_for_xml(XML)
        for iface in info.interfaces:
            conn.register_object(PATH, iface, self._call, self._get, self._set)
        Gio.bus_own_name_on_connection(conn, NAME, Gio.BusNameOwnerFlags.NONE, None, None)

    # --- properties ----------------------------------------------------------
    def _metadata(self):
        t = self.deck.tape
        if not t.name:
            return {"mpris:trackid": GLib.Variant("o", _track_path(None))}
        md = {
            "mpris:trackid": GLib.Variant("o", _track_path(t.uri)),
            "xesam:title": GLib.Variant("s", t.name),
            "xesam:artist": GLib.Variant("as", [a for a in t.artists.split(", ") if a]),
            "xesam:album": GLib.Variant("s", t.album or ""),
            "mpris:length": GLib.Variant("x", int(t.duration_ms) * 1000),
            "xesam:url": GLib.Variant("s", "https://open.spotify.com/track/" + (t.uri or "").split(":")[-1]),
        }
        covers = " ".join(t.covers).replace("|", " ").split()
        if covers:
            md["mpris:artUrl"] = GLib.Variant("s", covers[0])   # largest first in librespot's list
        return md

    def _props(self):
        t, d = self.deck.tape, self.deck
        ok = d.sp is not None
        return {
            ROOT: {
                "CanQuit": GLib.Variant("b", True),
                "CanRaise": GLib.Variant("b", True),
                "HasTrackList": GLib.Variant("b", False),
                "Identity": GLib.Variant("s", "TAPEDECK"),
                "DesktopEntry": GLib.Variant("s", "tapedeck"),
                "SupportedUriSchemes": GLib.Variant("as", ["spotify"]),
                "SupportedMimeTypes": GLib.Variant("as", []),
            },
            PLAYER: {
                "PlaybackStatus": GLib.Variant("s", STATUS[t.mode] if t.name else "Stopped"),
                "Rate": GLib.Variant("d", 1.0),
                "MinimumRate": GLib.Variant("d", 1.0),
                "MaximumRate": GLib.Variant("d", 1.0),
                "Metadata": GLib.Variant("a{sv}", self._metadata()),
                "Volume": GLib.Variant("d", (d.vol.get_value() or 0) / 100),
                "Position": GLib.Variant("x", int(t.position()) * 1000 if t.name else 0),
                "CanGoNext": GLib.Variant("b", ok),
                "CanGoPrevious": GLib.Variant("b", ok),
                "CanPlay": GLib.Variant("b", ok),
                "CanPause": GLib.Variant("b", ok),
                "CanSeek": GLib.Variant("b", ok and bool(t.name)),
                "CanControl": GLib.Variant("b", True),
            },
        }

    def _get(self, conn, sender, path, iface, prop):
        return self._props()[iface][prop]

    def _set(self, conn, sender, path, iface, prop, value):
        if prop == "Volume":
            self.deck.vol.set_value(max(0.0, min(1.0, value.unpack())) * 100)
        return True

    def changed(self, seeked=False):
        """Announce whatever differs from what listeners last saw (Position is never announced)."""
        now = self._props()[PLAYER]
        diff = {k: v for k, v in now.items() if k != "Position" and self.sent.get(k) != v}
        if diff:
            self.sent.update(diff)
            self.conn.emit_signal(None, PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                  GLib.Variant("(sa{sv}as)", (PLAYER, diff, [])))
        if seeked:
            self.conn.emit_signal(None, PATH, PLAYER, "Seeked",
                                  GLib.Variant("(x)", (int(self.deck.tape.position()) * 1000,)))

    # --- methods -------------------------------------------------------------
    def _call(self, conn, sender, path, iface, method, args, inv):
        d, a = self.deck, args.unpack()
        if method == "Raise":
            d.present()
        elif method == "Quit":
            d.quit()
        elif method == "Seek":
            d.seek_by(a[0] // 1000)
        elif method == "SetPosition":
            if a[0] == _track_path(d.tape.uri):
                d.seek_by(a[1] // 1000 - d.tape.position())
        elif method == "OpenUri":
            d.play_uris([a[0]], 0) if a[0].startswith("spotify:track:") else d.play_context(a[0])
        else:
            {"Next": d.next, "Previous": d.previous, "Pause": d.pause, "PlayPause": d.play_pause,
             "Stop": d.stop, "Play": d.play}[method]()
        inv.return_value(None)

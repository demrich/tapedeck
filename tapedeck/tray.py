"""Tray: an XEmbed status icon (the XFCE panel's systray takes it) so closing the deck hides it
there instead of quitting. Left click shows/hides the deck, right click is a small transport menu.
GtkStatusIcon is deprecated but needs no extra library and costs nothing while idle."""

import warnings

from gi.repository import Gtk

ICON = "multimedia-player"


class Tray:
    def __init__(self, deck):
        self.deck = deck
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self.icon = Gtk.StatusIcon.new_from_icon_name(ICON)
        self.icon.set_title("TAPEDECK")
        self.icon.connect("activate", lambda *_a: self.toggle())
        self.icon.connect("popup-menu", self._popup)
        self.menu = None
        self.update()

    def docked(self):
        """True when a panel systray is actually showing the icon (else closing must quit)."""
        return self.icon.is_embedded()

    def toggle(self):
        d = self.deck
        if d.get_visible() and not d.hidden:
            d.to_tray()
        else:
            d.from_tray()

    def update(self):
        t = self.deck.tape
        if not t.name:
            tip = "TAPEDECK"
        else:
            state = {"play": "Playing", "pause": "Paused"}.get(t.mode, "Stopped")
            tip = f"TAPEDECK — {state}\n{t.name}\n{t.artists}"
        self.icon.set_tooltip_text(tip)

    def _popup(self, icon, button, time):
        d = self.deck
        if self.menu:
            self.menu.destroy()
        self.menu = m = Gtk.Menu()
        shown = d.get_visible() and not d.hidden
        playing = d.tape.mode == "play"
        for label, fn in [("_Hide Deck" if shown else "_Show Deck", self.toggle), None,
                          ("_Pause" if playing else "_Play", d.play_pause),
                          ("_Next", d.next), ("P_revious", d.previous), None,
                          ("E_xit", d.quit)]:
            if label is None:
                m.append(Gtk.SeparatorMenuItem())
                continue
            item = Gtk.MenuItem.new_with_mnemonic(label)
            item.connect("activate", lambda _i, f=fn: f())
            m.append(item)
        m.show_all()
        m.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, time)

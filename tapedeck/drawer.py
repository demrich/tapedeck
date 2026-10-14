"""The drawer: cassettes (playlists, Liked Songs), search results and the queue in a themed list.

Everything loads lazily: nothing is fetched until the drawer is first opened. Tracklists are cached
in ~/.cache/haven/tapedeck/ and only refetched when Spotify says they changed (playlist snapshot_id,
or Liked Songs' total and newest track).

Development-mode apps can't read the tracklists of playlists the user doesn't own. Those are
"sealed cassettes": they still play, and their tracklist is filled in as tracks are heard.
"""
import json
import os

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango

from .display import mmss
from .spotify import SpotifyError

CACHE = os.path.expanduser("~/.cache/haven/tapedeck")
LIKED, SEARCH, QUEUE = "liked", "search", "queue"
SEARCH_MAX = 1000          # the Web API refuses offsets beyond this

# ListStore columns
C_IDX, C_NUM, C_TITLE, C_ARTIST, C_TIP, C_TIME, C_URI, C_WEIGHT, C_KIND = range(9)


def track_row(t):
    """Normalize a Web API track (or episode) object to [title, artist, album, duration_ms, uri]."""
    if not t or not t.get("uri"):
        return None
    artists = ", ".join(a["name"] for a in t.get("artists") or []) or (t.get("show") or {}).get("name", "")
    return [t.get("name") or "?", artists, (t.get("album") or {}).get("name", ""), t.get("duration_ms") or 0, t["uri"]]


def page_rows(page):
    rows = (track_row(e.get("item") or e.get("track")) for e in page.get("items", []))
    return [r for r in rows if r]


def load_cache(name):
    try:
        with open(os.path.join(CACHE, name + ".json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_cache(name, data):
    path = os.path.join(CACHE, name + ".json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(data, f)
    os.replace(path + ".tmp", path)


class Drawer(Gtk.Box):
    def __init__(self, deck):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4, border_width=6)
        self.deck = deck
        self.opened = False
        self.me = None
        self.cassettes = {}       # id -> {name, uri, sealed, snapshot}
        self.current = None
        self.rows = []            # rows of the cassette on display
        self.loading = None       # cassette id currently being fetched page by page
        self.search_q = ""
        self.search_rows = []
        self.search_total = 0
        self.playing = (None, None, None)   # uri, title, artists of the track on the deck

        top = Gtk.Box(spacing=4)
        lab = Gtk.Label.new_with_mnemonic("_Cassette:")
        self.combo = Gtk.ComboBoxText()
        self.combo.set_size_request(200, -1)
        for cell in self.combo.get_cells():   # long playlist names must not widen the whole deck
            cell.set_property("ellipsize", Pango.EllipsizeMode.END)
            cell.set_property("max-width-chars", 18)
        self.combo.connect("changed", self._on_combo)
        lab.set_mnemonic_widget(self.combo)
        play = Gtk.Button.new_with_mnemonic("Play _Tape")
        play.set_image(Gtk.Image.new_from_icon_name("media-playback-start", Gtk.IconSize.MENU))
        play.set_always_show_image(True)
        play.set_tooltip_text("Play this cassette from the start")
        play.connect("clicked", lambda _b: self.play_cassette())
        self.entry = Gtk.Entry(placeholder_text="Search Spotify  ( / )")
        self.entry.set_width_chars(10)
        self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "edit-find")
        self.entry.connect("activate", lambda e: self.search(e.get_text().strip()))
        self.entry.connect("key-press-event", self._on_entry_key)
        top.pack_start(lab, False, False, 0)
        top.pack_start(self.combo, False, False, 0)
        top.pack_start(play, False, False, 0)
        top.pack_start(self.entry, True, True, 0)
        self.pack_start(top, False, False, 0)

        self.store = Gtk.ListStore(int, str, str, str, str, str, str, int, str)
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.set_enable_search(False)      # the search box above is the real search
        self.tree.set_tooltip_column(C_TIP)
        self.tree.connect("row-activated", lambda _t, path, _c: self.play_row(path[0]))
        self.tree.connect("button-press-event", self._on_tree_button)
        for title, col, width, expand in [("#", C_NUM, 36, False), ("Title", C_TITLE, 190, True),
                                          ("Artist", C_ARTIST, 140, False), ("Time", C_TIME, 50, False)]:
            cell = Gtk.CellRendererText()
            if col in (C_TITLE, C_ARTIST):
                cell.set_property("ellipsize", Pango.EllipsizeMode.END)
            if col in (C_NUM, C_TIME):
                cell.set_property("xalign", 1.0)
            c = Gtk.TreeViewColumn(title, cell, text=col, weight=C_WEIGHT)
            c.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            c.set_fixed_width(width)
            c.set_expand(expand)
            self.tree.append_column(c)
        sw = Gtk.ScrolledWindow(shadow_type=Gtk.ShadowType.IN)
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_min_content_height(240)
        sw.add(self.tree)
        self.pack_start(sw, True, True, 0)

        self.menu = Gtk.Menu()
        for label, cb in [("_Play", self._menu_play), ("Add to _Queue  (Q)", self.queue_selected)]:
            mi = Gtk.MenuItem.new_with_mnemonic(label)
            mi.connect("activate", lambda _m, f=cb: f())
            self.menu.append(mi)
        self.menu.show_all()

    # --- opening + cassette list --------------------------------------------
    def open(self):
        """First open: show the cached cassette list at once, then refresh it from Spotify."""
        if self.opened:
            return
        self.opened = True
        cached = load_cache("playlists")
        if cached:
            self.me = cached["me"]
            self._set_cassettes(cached["items"])
        else:
            self._set_cassettes([])
        self.show(LIKED)   # _set_cassettes already selected it (with the handler blocked)
        if self.deck.sp:
            self.refresh_cassettes()

    def refresh_cassettes(self):
        sp = self.deck.sp
        def job():
            me = self.me or sp.me()["id"]
            items, offset = [], 0
            while True:
                page = sp.playlists(offset)
                for p in page["items"]:
                    if not p:
                        continue
                    items.append({"id": p["id"], "name": p["name"], "uri": p["uri"],
                                  "sealed": p["owner"]["id"] != me, "snapshot": p.get("snapshot_id")})
                offset += len(page["items"])
                if not page.get("next"):
                    return me, items
        def done(res):
            self.me, items = res
            save_cache("playlists", {"me": self.me, "items": items})
            self._set_cassettes(items)
        self.deck.api(job, lane="lib", done=done)

    def _set_cassettes(self, items):
        old, self.cassettes = self.cassettes, {p["id"]: p for p in items}
        keep = self.combo.get_active_id()
        self.combo.handler_block_by_func(self._on_combo)
        self.combo.remove_all()
        self.combo.append(LIKED, "Liked Songs")
        self.combo.append(SEARCH, "Search Results")
        self.combo.append(QUEUE, "Up Next (queue)")
        for p in sorted(items, key=lambda p: p["sealed"]):   # own tapes first, sealed after
            self.combo.append(p["id"], p["name"] + ("  [sealed]" if p["sealed"] else ""))
        self.combo.set_active_id(keep or LIKED)
        self.combo.handler_unblock_by_func(self._on_combo)
        new = self.cassettes.get(keep)
        if new and (keep not in old or old[keep]["snapshot"] != new["snapshot"]):
            self.show(keep)   # the tape on display changed on Spotify's side: reload it

    def _on_combo(self, combo):
        cid = combo.get_active_id()
        if cid:
            self.show(cid)

    # --- showing a cassette ------------------------------------------------
    def show(self, cid):
        self.current = cid
        self.loading = None
        if cid == SEARCH:
            self._fill(self.search_rows, more=self._search_has_more())
            self._summary("Search: " + (self.search_q or "type in the box above"))
        elif cid == QUEUE:
            self._fill([])
            self.load_queue()
        elif cid == LIKED:
            cached = load_cache("liked")
            self._fill(cached["rows"] if cached else [])
            self._load_liked(cached)
        else:
            p = self.cassettes[cid]
            if p["sealed"]:
                cached = load_cache("sealed/" + cid)
                self._fill(cached or [])
                self.deck.say(f"SEALED CASSETTE: {len(cached or [])} tracks heard so far. "
                              "Spotify keeps this tracklist private; it fills in as you play it")
                return
            cached = load_cache("tapes/" + cid)
            if cached and cached.get("snapshot") == p["snapshot"]:
                self._fill(cached["rows"])
                self._summary(p["name"])
            else:
                self._fill([])   # self.rows is filled page by page as the load progresses
                self._fetch(cid, lambda off: self.deck.sp.playlist_items(cid, off, 100), self.rows,
                            lambda rows: save_cache("tapes/" + cid, {"snapshot": p["snapshot"], "rows": rows}))

    def _load_liked(self, cached):
        sp = self.deck.sp
        if not sp:
            return
        def first(page):
            if self.current != LIKED:
                return
            rows = page_rows(page)
            sig = [page["total"], rows[0][4] if rows else None]
            if cached and cached.get("sig") == sig:
                self._summary("Liked Songs")
                return
            self._fill([])
            self._got_page(LIKED, page, lambda off: sp.liked(off, 50), self.rows,
                           lambda all_rows: save_cache("liked", {"sig": sig, "rows": all_rows}))
        self.deck.say("REWINDING TAPE...")
        self.deck.api(sp.liked, 0, 50, lane="lib", done=first)

    def _fetch(self, cid, fetch, acc, finish, offset=0):
        self.loading = cid
        self.deck.say("REWINDING TAPE...")
        self.deck.api(fetch, offset, lane="lib",
                      done=lambda page: self._got_page(cid, page, fetch, acc, finish))

    def _got_page(self, cid, page, fetch, acc, finish):
        if self.current != cid:      # user switched cassettes; drop the rest of this load
            return
        rows = page_rows(page)
        self._append(rows, len(acc))
        acc.extend(rows)
        total = page.get("total") or len(acc)
        if page.get("next") and page.get("items"):
            self.deck.say(f"REWINDING TAPE... {len(acc)}/{total}")
            self._fetch(cid, fetch, acc, finish, page["offset"] + len(page["items"]))
        else:
            self.loading = None
            finish(acc)
            self._summary(self.cassettes[cid]["name"] if cid in self.cassettes else "Liked Songs")

    def load_queue(self):
        if not self.deck.sp:
            return
        def done(q):
            if self.current != QUEUE:
                return
            rows = [r for r in (track_row(t) for t in (q or {}).get("queue", [])) if r]
            self._fill(rows)
            self._summary("Up Next")
        self.deck.api(self.deck.sp.queue, lane="lib", done=done)

    def _fill(self, rows, more=False):
        self.rows = []
        self.store.clear()
        self._append(rows, 0)
        self.rows = list(rows)
        if more:
            self._add_more_row()

    def _append(self, rows, start):
        for i, (title, artist, album, dur, uri) in enumerate(rows, start):
            tip = GLib.markup_escape_text(f"{title}\n{artist}\n{album}")
            self.store.append([i, str(i + 1), title, artist, tip, mmss(dur), uri, Pango.Weight.NORMAL, "track"])
        if rows:
            self._remark()

    def _summary(self, name):
        total = sum(r[3] for r in self.rows)
        h, m, s = total // 3600000, total // 60000 % 60, total // 1000 % 60
        length = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        self.deck.say(f"{name}: {len(self.rows)} tracks, {length}")

    # --- now-playing marker + sealed cassettes ------------------------------
    def mark_playing(self, uri, name, artists):
        self.playing = (uri, name, artists)
        self._remark()

    def _remark(self):
        """Bold + arrow on exactly one row: the URI match, else (relinked track) title and artist."""
        uri, name, artists = self.playing
        rows = [r for r in self.store if r[C_KIND] == "track"]
        hit = next((r[C_IDX] for r in rows if r[C_URI] == uri), None)
        if hit is None and name:
            hit = next((r[C_IDX] for r in rows if r[C_TITLE] == name and r[C_ARTIST] == artists), None)
        for r in rows:
            now = r[C_IDX] == hit
            if (r[C_WEIGHT] == Pango.Weight.BOLD) != now:
                r[C_NUM] = "▶" if now else str(r[C_IDX] + 1)
                r[C_WEIGHT] = Pango.Weight.BOLD if now else Pango.Weight.NORMAL

    def heard(self, context_uri, item):
        """A track started in some context; if it's a sealed cassette, write it onto the tracklist."""
        if not context_uri or not context_uri.startswith("spotify:playlist:"):
            return
        cid = context_uri.rsplit(":", 1)[1]
        if not self.cassettes.get(cid, {}).get("sealed"):
            return
        row = track_row(item)
        rows = load_cache("sealed/" + cid) or []
        if not row or any(r[4] == row[4] for r in rows):
            return
        rows.append(row)
        save_cache("sealed/" + cid, rows)
        if self.current == cid:
            self._append([row], len(self.rows))
            self.rows.append(row)

    # --- search ------------------------------------------------------------
    def focus_search(self):
        self.entry.grab_focus()

    def _on_entry_key(self, _e, ev):
        if ev.keyval == 0xff1b:   # Escape: back to the list
            self.tree.grab_focus()
            return True
        return False

    def _search_has_more(self):
        return bool(self.search_rows) and len(self.search_rows) < min(self.search_total, SEARCH_MAX)

    def search(self, q, more=False):
        if not q or self.deck._need_login():
            return
        if not more:
            self.search_q, self.search_rows, self.search_total = q, [], 0
        offset = len(self.search_rows)
        def done(res):
            tracks = res.get("tracks", {})
            self.search_total = tracks.get("total", 0)
            self.search_rows += [r for r in (track_row(t) for t in tracks.get("items", [])) if r]
            if self.combo.get_active_id() != SEARCH:
                self.combo.set_active_id(SEARCH)   # triggers show()
            else:
                self.show(SEARCH)
            if self.search_rows:
                self.tree.grab_focus()
                self.tree.set_cursor(Gtk.TreePath(offset if more else 0), None, False)
        self.deck.say("SEEKING...")
        self.deck.api(self.deck.sp.search, q, "track", 10, offset, lane="lib", done=done)

    def _add_more_row(self):
        self.store.append([-1, "", "[ more results... ]", "", "", "", "", Pango.Weight.NORMAL, "more"])

    # --- playing -----------------------------------------------------------
    def _selected(self):
        model, it = self.tree.get_selection().get_selected()
        return model.get_path(it)[0] if it else None

    def _menu_play(self):
        i = self._selected()
        if i is not None:
            self.play_row(i)

    def play_row(self, i):
        if self.deck._need_login():
            return
        if self.store[i][C_KIND] == "more":
            self.search(self.search_q, more=True)
            return
        uri = self.store[i][C_URI]
        cid = self.current
        uris = [r[4] for r in self.rows]
        if cid in self.cassettes:
            self.deck.play_context(self.cassettes[cid]["uri"], offset=uri)
        elif cid == LIKED and self.me:
            # Liked Songs as a context; if Spotify refuses, fall back to a window of track URIs
            self.deck.play_context(f"spotify:user:{self.me}:collection", offset=uri,
                                   fallback=uris[i:i + 100])
        else:   # search results, queue, or Liked Songs before we know the user id
            self.deck.play_uris(uris[i:i + 100] if cid != SEARCH else uris, 0 if cid != SEARCH else i)

    def play_cassette(self):
        cid = self.current
        if self.deck._need_login() or cid is None:
            return
        if cid in self.cassettes:
            self.deck.play_context(self.cassettes[cid]["uri"])
        elif cid == LIKED and self.me:
            self.deck.play_context(f"spotify:user:{self.me}:collection", fallback=[r[4] for r in self.rows[:100]])
        elif self.rows:
            self.deck.play_uris([r[4] for r in self.rows[:100]], 0)

    def queue_selected(self):
        i = self._selected()
        if i is None or self.store[i][C_KIND] != "track" or self.deck._need_login():
            return
        title = self.store[i][C_TITLE]
        def done(_r):
            self.deck.say(f"Queued: {title}")
            if self.current == QUEUE:
                self.load_queue()
        self.deck.api(self.deck.sp.add_to_queue, self.store[i][C_URI], done=done)

    def _on_tree_button(self, tree, ev):
        if ev.button != 3:
            return False
        hit = tree.get_path_at_pos(int(ev.x), int(ev.y))
        if hit:
            tree.set_cursor(hit[0], None, False)
            self.menu.popup_at_pointer(ev)
        return True

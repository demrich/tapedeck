"""The drawer: cassettes (playlists, Liked Songs), search results and the queue in a themed list.

Everything loads lazily: nothing is fetched until the drawer is first opened. Tracklists are cached
in ~/.cache/haven/tapedeck/ and only refetched when Spotify says they changed (playlist snapshot_id,
or Liked Songs' total and newest track).

Development-mode apps can't read the tracklists of playlists the user doesn't own. Those are
"sealed cassettes": they still play, and their tracklist is filled in as tracks are heard.

Browsing pages (artist, album, radio) appear in the cassette list too, with a Back history.
Spotify withholds top tracks, related artists and radio from development-mode apps, so those
come from Deezer's public API and are matched back to Spotify tracks by search.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango

from . import deezer
from .display import mmss

CACHE = os.path.expanduser("~/.cache/haven/tapedeck")
LIKED, SEARCH, QUEUE = "liked", "search", "queue"
SEARCH_MAX = 1000          # the Web API refuses offsets beyond this
PAGES = ("artist:", "album:", "radio:")
MAX_PAGES = 30             # browsing pages kept in memory for Back
ALBUM_TYPES = {"album": "Album", "single": "Single", "compilation": "Compilation"}

# ListStore columns
C_IDX, C_NUM, C_TITLE, C_ARTIST, C_TIP, C_TIME, C_URI, C_WEIGHT, C_KIND = range(9)


def track_row(t):
    """Normalize a Web API track (or episode) object to [title, artist, album, duration_ms, uri]."""
    if not t or not t.get("uri"):
        return None
    artists = ", ".join(a["name"] for a in t.get("artists") or []) or (t.get("show") or {}).get("name", "")
    return [t.get("name") or "?", artists, (t.get("album") or {}).get("name", ""), t.get("duration_ms") or 0, t["uri"]]


def album_item(al, sub=None):
    """A nav row for an album: (kind, title, sub, time, uri). Singles of 4+ tracks are EPs."""
    kind = ALBUM_TYPES.get(al.get("album_type"), "Album")
    if kind == "Single" and (al.get("total_tracks") or 0) >= 4:
        kind = "EP"
    if sub is None:
        sub = kind
    else:
        sub = f"{kind}: {sub}"
    return ("album", al["name"], sub, (al.get("release_date") or "")[:4], al["uri"])


def length(rows):
    total = sum(r[3] for r in rows)
    h, m, s = total // 3600000, total // 60000 % 60, total // 1000 % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


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
        self.search_extra = []    # artist + album rows above the track results (first page only)
        self.playing = (None, None, None)   # uri, title, artists of the track on the deck
        self.pages = {}           # browsing page id -> {label, items, status}
        self.page_entry = None    # (id, label) of the browsing page listed in the combo
        self.history = []         # cassette/page ids for Back
        self._going_back = False

        top = Gtk.Box(spacing=4)
        back = Gtk.Button()
        back.add(Gtk.Image.new_from_icon_name("go-previous", Gtk.IconSize.MENU))
        back.set_tooltip_text("Back (Backspace)")
        back.connect("clicked", lambda _b: self.back())
        top.pack_start(back, False, False, 0)
        lab = Gtk.Label.new_with_mnemonic("_Cassette:")
        self.combo = Gtk.ComboBoxText()
        self.combo.set_size_request(165, -1)
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
        sw.set_overlay_scrolling(False)   # a real scrollbar that never covers the Time column
        sw.set_min_content_height(240)
        sw.add(self.tree)
        self.pack_start(sw, True, True, 0)

        self.menu = Gtk.Menu()
        for item in [("_Play", self._menu_play), ("Add to _Queue  (Q)", self.queue_selected), None,
                     ("Go to _Artist  (A)", self.key_artist), ("Go to Al_bum  (B)", self.key_album),
                     ("Start _Radio  (R)", self.key_radio)]:
            if item is None:
                self.menu.append(Gtk.SeparatorMenuItem())
                continue
            label, cb = item
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

    def _set_cassettes(self, items, select=None):
        old, self.cassettes = self.cassettes, {p["id"]: p for p in items}
        keep = self.combo.get_active_id()
        if keep and keep.startswith(PAGES) and (not self.page_entry or self.page_entry[0] != keep):
            keep = None
        self.combo.handler_block_by_func(self._on_combo)
        self.combo.remove_all()
        self.combo.append(LIKED, "Liked Songs")
        self.combo.append(SEARCH, "Search Results")
        self.combo.append(QUEUE, "Up Next (queue)")
        if self.page_entry:
            self.combo.append(*self.page_entry)
        for p in sorted(items, key=lambda p: p["sealed"]):   # own tapes first, sealed after
            self.combo.append(p["id"], p["name"] + ("  [sealed]" if p["sealed"] else ""))
        self.combo.set_active_id(keep or LIKED)
        self.combo.handler_unblock_by_func(self._on_combo)
        if select:
            self.combo.set_active_id(select)   # emits changed -> _on_combo
            return
        new = self.cassettes.get(keep)
        if new and (keep not in old or old[keep]["snapshot"] != new["snapshot"]):
            self.show(keep)   # the tape on display changed on Spotify's side: reload it

    def _on_combo(self, combo):
        cid = combo.get_active_id()
        if cid and cid != self.current:
            if self.current and not self._going_back:
                self.history = (self.history + [self.current])[-50:]
            self.show(cid)

    # --- browsing pages + Back ---------------------------------------------
    def goto(self, cid):
        """Show a browsing page: it takes the combo's page slot and becomes the cassette on display."""
        self.open()
        self.deck.open_drawer()
        self.page_entry = (cid, "» " + self.pages[cid]["label"])
        if self.current == cid:
            self.show(cid)
        else:
            self._set_cassettes(list(self.cassettes.values()), select=cid)

    def back(self):
        while self.history:
            cid = self.history.pop()
            if cid in (LIKED, SEARCH, QUEUE) or cid in self.cassettes or cid in self.pages:
                break
        else:
            self.deck.say("Nothing to go back to")
            return
        self._going_back = True
        if cid.startswith(PAGES):
            self.page_entry = (cid, "» " + self.pages[cid]["label"])
            self._set_cassettes(list(self.cassettes.values()), select=cid)
        else:
            self.combo.set_active_id(cid)
        self._going_back = False

    def _new_page(self, cid, label):
        if len(self.pages) >= MAX_PAGES:   # drop the oldest page that isn't on display
            del self.pages[next(c for c in self.pages if c != self.current)]
        self.pages[cid] = {"label": label, "items": [], "status": "PULLING THE J-CARD..."}

    def _page_update(self, cid, label, items, status):
        pg = self.pages.get(cid)
        if pg is None:
            return
        pg.update(label=label, items=items, status=status)
        if self.page_entry and self.page_entry[0] == cid and self.page_entry[1] != "» " + label:
            self.page_entry = (cid, "» " + label)
            self._set_cassettes(list(self.cassettes.values()))
        if self.current == cid:
            cur = self._selected()
            self.show(cid)
            if cur is not None and cur < len(self.store):
                self.tree.set_cursor(Gtk.TreePath(cur), None, False)

    def goto_artist(self, aid, name=None):
        cid = "artist:" + aid
        if cid not in self.pages:
            self._new_page(cid, name or "Artist")
            self._load_artist(cid, aid)
        self.goto(cid)

    def _load_artist(self, cid, aid):
        """Two stages: Spotify's artist + albums first, then Deezer's popular tracks and look-alikes."""
        sp = self.deck.sp

        def spotify_part():
            a, albums, off = sp.artist(aid), [], 0
            while off < 50:
                pg = sp.artist_albums(aid, off)
                albums += [x for x in pg["items"] if x]
                off += len(pg["items"])
                if not pg.get("next") or not pg["items"]:
                    return a, albums
            return a, albums

        def deezer_part(name, titles):
            did = deezer.find_artist(name, titles)
            if not did:
                return [], []
            with ThreadPoolExecutor(5) as ex:
                found = list(ex.map(lambda t: sp.find_track(*t), deezer.top(did, 5)))
            return [r for r in (track_row(t) for t in found) if r], deezer.related(did, 12)

        def build(a, albums, popular, similar, note=""):
            seen, full, short = set(), [], []
            for al in albums:
                if al["name"].casefold() not in seen:
                    seen.add(al["name"].casefold())
                    (full if al.get("album_type") == "album" else short).append(album_item(al))
            items = [("radio", f"{a['name']} Radio", "Similar music, via Deezer", "", a["name"])]
            uris = set()
            popular = [r for r in popular if not (r[4] in uris or uris.add(r[4]))]
            for head, group in [("POPULAR", [("track", r) for r in popular]), ("ALBUMS", full),
                                ("SINGLES & EPS", short),
                                ("FANS ALSO LIKE", [("artist", n, "Artist", "", "dz:" + n) for n in similar])]:
                if group:
                    items += [("head", head)] + group
            status = f"{a['name']}: {len(full)} albums, {len(short)} singles & EPs{note}"
            self._page_update(cid, a["name"], items, status)

        def stage1(res):
            a, albums = res
            build(a, albums, [], [], "  (looking up similar artists...)")
            self.deck.api(deezer_part, a["name"], [x["name"] for x in albums], lane="lib",
                          done=lambda d: build(a, albums, *d),
                          fail=lambda e: build(a, albums, [], [], "  (similar artists unavailable)"))
        self.deck.api(spotify_part, lane="lib", done=stage1,
                      fail=lambda e: self._page_update(cid, "Artist", [], f"HEAD CLEANING REQUIRED: {e}"))

    def goto_album(self, aid, name=None):
        cid = "album:" + aid
        if cid not in self.pages:
            self._new_page(cid, name or "Album")
            self._load_album(cid, aid)
        self.goto(cid)

    def _load_album(self, cid, aid):
        sp = self.deck.sp

        def job():
            al = sp.album(aid)
            tracks, page = [], al["tracks"]
            while True:
                tracks += [t for t in page["items"] if t]
                if not page.get("next") or not page["items"]:
                    return al, tracks
                page = sp.album_tracks(aid, len(tracks))

        def done(res):
            al, tracks = res
            rows = []
            for t in tracks:
                row = track_row(t)
                if row:
                    row[2] = al["name"]
                    rows.append(row)
            year = (al.get("release_date") or "")[:4]
            items = [("artist", a["name"], "Artist", "", a["uri"]) for a in al.get("artists", [])[:3]]
            items += [("head", " · ".join(x for x in (al["name"].upper(), year, al.get("label")) if x))]
            items += [("track", r) for r in rows]
            self._page_update(cid, al["name"], items,
                              f"{al['name']} ({year}): {len(rows)} tracks, {length(rows)}")
        self.deck.api(job, lane="lib", done=done,
                      fail=lambda e: self._page_update(cid, "Album", [], f"HEAD CLEANING REQUIRED: {e}"))

    def start_radio(self, name, seed=None, titles=None):
        """Artist radio: Deezer's mix for the artist, matched to Spotify tracks, played as a list.
        A seed track (the one the radio was started from) plays first."""
        if self.deck._need_login():
            return
        sp = self.deck.sp
        cid = "radio:" + name.casefold()

        def job():
            did = (seed and deezer.artist_of_track(seed[0], name)) or deezer.find_artist(name, titles)
            if not did:
                raise RuntimeError(f"no radio station for {name}")
            with ThreadPoolExecutor(5) as ex:
                found = list(ex.map(lambda t: sp.find_track(*t), deezer.radio(did)))
            return [r for r in (track_row(t) for t in found) if r]

        def done(rows):
            if seed:
                rows = [seed] + rows
            seen = set()
            rows = [r for r in rows if not (r[4] in seen or seen.add(r[4]))]
            if not rows:
                self.deck.say(f"STATIC ON {name.upper()} RADIO: nothing matched")
                return
            if cid not in self.pages:
                self._new_page(cid, f"{name} Radio")
            items = [("head", f"{name.upper()} RADIO · {len(rows)} TRACKS")] + [("track", r) for r in rows]
            self.pages[cid].update(items=items, status=f"{name} Radio: {len(rows)} tracks, {length(rows)}")
            self.goto(cid)
            # radio from the song in the deck: it keeps playing where it is, the station follows
            t = self.deck.tape
            pos = t.position() if seed and seed[4] == t.uri and t.mode == "play" else None
            self.deck.play_uris([r[4] for r in rows], 0, pos)
        self.deck.say(f"TUNING {name.upper()} RADIO...")
        self.deck.api(job, lane="lib", done=done)

    # A / B / R act on the selected row while the list has focus, else on the track in the deck.
    def _target(self):
        if self.deck.revealer.get_reveal_child() and self.tree.is_focus():
            i = self._selected()
            if i is not None:
                r = self.store[i]
                if r[C_KIND] == "track":
                    return "track", self.rows[r[C_IDX]]
                if r[C_KIND] in ("artist", "album"):
                    return r[C_KIND], (r[C_TITLE], r[C_URI])
        return self._deck_target()

    def _deck_target(self):
        t = self.deck.tape
        if t.uri:
            return "track", [t.name, t.artists, t.album, t.duration_ms, t.uri]
        self.deck.say("INSERT CASSETTE: nothing selected or playing")
        return None, None

    def _with_track(self, row, then):
        """Fetch the full track (artist and album ids) for a track row, then call then(track)."""
        if not row[4].startswith("spotify:track:") or self.deck._need_login():
            self.deck.say("No catalog page for this tape")
            return
        self.deck.api(self.deck.sp.track, row[4].rsplit(":", 1)[1], lane="lib", done=then)

    def open_artist(self, name, uri):
        if uri.startswith("spotify:artist:"):
            self.goto_artist(uri.rsplit(":", 1)[1], name)
            return
        def done(a):   # a Deezer look-alike: find the Spotify artist by name
            if a:
                self.goto_artist(a["id"], a["name"])
            else:
                self.deck.say(f"{name}: not on Spotify")
        self.deck.say(f"Finding {name}...")
        self.deck.api(self.deck.sp.find_artist, name, lane="lib", done=done)

    def key_artist(self, target=None):
        kind, t = target or self._target()
        if kind == "artist":
            self.open_artist(*t)
        elif kind == "track":
            self._with_track(t, lambda tr: self.goto_artist(tr["artists"][0]["id"], tr["artists"][0]["name"]))

    def key_album(self, target=None):
        kind, t = target or self._target()
        if kind == "album":
            self.goto_album(t[1].rsplit(":", 1)[1], t[0])
        elif kind == "track":
            self._with_track(t, lambda tr: self.goto_album(tr["album"]["id"], tr["album"]["name"]))

    def key_radio(self, target=None):
        kind, t = target or self._target()
        if kind == "artist":
            self.start_radio(t[0])
        elif kind == "track":
            self._with_track(t, lambda tr: self.start_radio(tr["artists"][0]["name"], seed=t,
                                                            titles=[tr["album"]["name"]]))

    # --- showing a cassette ------------------------------------------------
    def show(self, cid):
        self.current = cid
        self.loading = None
        if cid.startswith(PAGES):
            pg = self.pages[cid]
            self._fill_items(pg["items"])
            self.deck.say(pg["status"])
        elif cid == SEARCH:
            items = list(self.search_extra) + ([("head", "TRACKS")] if self.search_extra else [])
            self._fill_items(items + [("track", r) for r in self.search_rows], more=self._search_has_more())
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
        self._fill_items([("track", r) for r in rows], more)

    def _fill_items(self, items, more=False):
        """Rows of mixed kinds: ("track", row), ("head", text), or a nav row
        ("album" | "artist" | "radio", title, sub, time, uri)."""
        self.rows = []
        self.store.clear()
        for it in items:
            if it[0] == "track":
                title, artist, album, dur, uri = it[1]
                i = len(self.rows)
                self.rows.append(it[1])
                tip = GLib.markup_escape_text(f"{title}\n{artist}\n{album}")
                self.store.append([i, str(i + 1), title, artist, tip, mmss(dur), uri, Pango.Weight.NORMAL, "track"])
            elif it[0] == "head":
                self.store.append([-1, "", it[1], "", "", "", "", Pango.Weight.BOLD, "head"])
            else:
                kind, title, sub, time, uri = it
                tip = GLib.markup_escape_text(f"{title}\n{sub}")
                self.store.append([-1, "▶" if kind == "radio" else "»", title, sub, tip, time, uri,
                                   Pango.Weight.NORMAL, kind])
        if more:
            self._add_more_row()
        self._remark()

    def _append(self, rows, start):
        for i, (title, artist, album, dur, uri) in enumerate(rows, start):
            tip = GLib.markup_escape_text(f"{title}\n{artist}\n{album}")
            self.store.append([i, str(i + 1), title, artist, tip, mmss(dur), uri, Pango.Weight.NORMAL, "track"])
        if rows:
            self._remark()

    def _summary(self, name):
        self.deck.say(f"{name}: {len(self.rows)} tracks, {length(self.rows)}")

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
            self.search_q, self.search_rows, self.search_total, self.search_extra = q, [], 0, []
        offset = len(self.search_rows)
        def done(res):
            if not more:
                artists = [a for a in res.get("artists", {}).get("items", []) if a][:3]
                albums = [a for a in res.get("albums", {}).get("items", []) if a][:3]
                self.search_extra = (
                    ([("head", "ARTISTS")] if artists else [])
                    + [("artist", a["name"], "Artist", "", a["uri"]) for a in artists]
                    + ([("head", "ALBUMS")] if albums else [])
                    + [album_item(a, ", ".join(x["name"] for x in a.get("artists", []))) for a in albums])
            tracks = res.get("tracks", {})
            self.search_total = tracks.get("total", 0)
            self.search_rows += [r for r in (track_row(t) for t in tracks.get("items", [])) if r]
            if self.combo.get_active_id() != SEARCH:
                self.combo.set_active_id(SEARCH)   # triggers show()
            else:
                self.show(SEARCH)
            if len(self.store):
                extra = len(self.search_extra) + (1 if self.search_extra else 0)
                self.tree.grab_focus()
                self.tree.set_cursor(Gtk.TreePath(extra + offset if more else 0), None, False)
        self.deck.say("SEEKING...")
        kinds = "track" if more else "artist,album,track"
        self.deck.api(self.deck.sp.search, q, kinds, 10, offset, lane="lib", done=done)

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
        row = self.store[i]
        kind, uri, title = row[C_KIND], row[C_URI], row[C_TITLE]
        if kind == "more":
            self.search(self.search_q, more=True)
            return
        if kind == "album":
            self.goto_album(uri.rsplit(":", 1)[1], title)
            return
        if kind == "artist":
            self.open_artist(title, uri)
            return
        if kind == "radio":
            self.start_radio(uri)
            return
        if kind != "track":
            return
        i = row[C_IDX]   # position among the tracks (nav and heading rows don't count)
        cid = self.current
        uris = [r[4] for r in self.rows]
        if cid.startswith("album:"):
            self.deck.play_context("spotify:" + cid, offset=uri)
        elif cid in self.cassettes:
            self.deck.play_context(self.cassettes[cid]["uri"], offset=uri)
        elif cid == LIKED and self.me:
            # Liked Songs as a context; if Spotify refuses, fall back to a window of track URIs
            self.deck.play_context(f"spotify:user:{self.me}:collection", offset=uri,
                                   fallback=uris[i:i + 100])
        elif cid == SEARCH or cid.startswith(PAGES):   # short lists: play them all from this track
            self.deck.play_uris(uris[:100], min(i, 99))
        else:   # the queue, or Liked Songs before we know the user id
            self.deck.play_uris(uris[i:i + 100], 0)

    def play_cassette(self):
        cid = self.current
        if self.deck._need_login() or cid is None:
            return
        if cid.startswith(("album:", "artist:")):   # artist context = Spotify's own artist mix
            self.deck.play_context("spotify:" + cid)
        elif cid in self.cassettes:
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

    # The Tape menu and clicks on the display always mean the tape in the deck.
    def goto_artist_of_deck(self):
        self.key_artist(self._deck_target())

    def goto_album_of_deck(self):
        self.key_album(self._deck_target())

    def radio_of_deck(self):
        self.key_radio(self._deck_target())

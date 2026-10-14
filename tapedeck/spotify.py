"""Minimal Spotify Web API client: PKCE login, token refresh, a few endpoints.

Stdlib only (urllib) to keep import time and RSS low.
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

CONFIG_DIR = os.path.expanduser("~/.config/haven/tapedeck")
TOKEN_FILE = os.path.join(CONFIG_DIR, "token.json")
CLIENT_FILE = os.path.join(CONFIG_DIR, "client_id")
REDIRECT_PORT = 8898
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
])
API = "https://api.spotify.com/v1"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"


class SpotifyError(Exception):
    def __init__(self, status, message):
        super().__init__(f"{status}: {message}")
        self.status = status


def _client_id():
    with open(CLIENT_FILE) as f:
        return f.read().strip()


def _post_form(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def _save_token(tok):
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    os.makedirs(CONFIG_DIR, exist_ok=True)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(tok, f)
    return tok


def login():
    """Interactive PKCE login: opens the browser, waits for the redirect."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": _client_id(),
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "scope": SCOPES,
        "state": state,
    }
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<body style='background:#c1c1c1;font-family:monospace'>"
                             b"<h2>TAPEDECK</h2><p>Cassette loaded. You may close this window.</p></body>")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), Handler)
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    print("Opening browser for Spotify login:\n" + url)
    webbrowser.open(url)
    while "code" not in result and "error" not in result:
        srv.handle_request()
    srv.server_close()
    if result.get("state") != state or "code" not in result:
        raise SpotifyError(0, f"login failed: {result.get('error', 'state mismatch')}")
    return _save_token(_post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "code": result["code"],
        "redirect_uri": REDIRECT_URI,
        "client_id": _client_id(),
        "code_verifier": verifier,
    }))


def _loose(title):
    """Titles compared loosely: no "(Remastered)" / " - Live" tails, case or punctuation."""
    title = title.split(" (")[0].split(" - ")[0].split(" [")[0]
    return "".join(c for c in title.casefold() if c.isalnum())


class Spotify:
    def __init__(self):
        with open(TOKEN_FILE) as f:
            self.tok = json.load(f)
        self._lock = threading.Lock()   # the UI uses two worker threads; refresh only once

    def _token(self):
        with self._lock:
            return self._token_locked()

    def _token_locked(self):
        if time.time() >= self.tok["expires_at"]:
            new = _post_form(TOKEN_URL, {
                "grant_type": "refresh_token",
                "refresh_token": self.tok["refresh_token"],
                "client_id": _client_id(),
            })
            new.setdefault("refresh_token", self.tok["refresh_token"])
            self.tok = _save_token(new)
        return self.tok["access_token"]

    def call(self, method, path, params=None, body=None):
        url = API + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else (b"" if method in ("PUT", "POST") else None)
        req = urllib.request.Request(url, data, method=method, headers={
            "Authorization": "Bearer " + self._token(),
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read()
                # player commands answer 200/204 with an empty or non-JSON body; only parse JSON
                if not raw.strip() or "json" not in (r.headers.get("Content-Type") or ""):
                    return None
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            try:
                msg = json.load(e).get("error", {}).get("message", e.reason)
            except Exception:
                msg = e.reason
            raise SpotifyError(e.code, msg) from None

    # --- library -----------------------------------------------------------
    def me(self):
        return self.call("GET", "/me")

    def search(self, q, kind="track", limit=10, offset=0):
        return self.call("GET", "/search", {"q": q, "type": kind, "limit": limit, "offset": offset})

    def playlists(self, offset=0, limit=50):
        return self.call("GET", "/me/playlists", {"offset": offset, "limit": limit})

    def playlist_items(self, pid, offset=0, limit=100):
        return self.call("GET", f"/playlists/{pid}/items", {"offset": offset, "limit": limit})

    def liked(self, offset=0, limit=50):
        return self.call("GET", "/me/tracks", {"offset": offset, "limit": limit})

    # --- catalog (browsing) -------------------------------------------------
    def track(self, tid):
        return self.call("GET", f"/tracks/{tid}")

    def artist(self, aid):
        return self.call("GET", f"/artists/{aid}")

    def artist_albums(self, aid, offset=0):
        # development mode caps this endpoint at 10 per page
        return self.call("GET", f"/artists/{aid}/albums",
                         {"include_groups": "album,single", "limit": 10, "offset": offset})

    def album(self, aid):
        return self.call("GET", f"/albums/{aid}")

    def album_tracks(self, aid, offset=0):
        return self.call("GET", f"/albums/{aid}/tracks", {"limit": 50, "offset": offset})

    def find_track(self, title, artist):
        """Spotify's copy of a song known by title + artist name (from Deezer), or None.
        A hit must agree on the artist and, loosely, the title: a wrong song is worse than none."""
        want = _loose(title)
        for q in (f'track:"{title}" artist:"{artist}"', f"{title} {artist}"):
            for t in self.search(q, "track", 5)["tracks"]["items"]:
                if not t or artist.casefold() not in (a["name"].casefold() for a in t["artists"]):
                    continue
                got = _loose(t["name"])
                if got == want or got.startswith(want) or want.startswith(got):
                    return t
        return None

    def find_artist(self, name):
        hits = [a for a in self.search(name, "artist", 5)["artists"]["items"] if a]
        exact = [a for a in hits if a["name"].casefold() == name.casefold()]
        return (exact or hits or [None])[0]

    # --- playback ----------------------------------------------------------
    def devices(self):
        return self.call("GET", "/me/player/devices")["devices"]

    def device_id(self, name="TAPEDECK"):
        for d in self.devices():
            if d["name"] == name:
                return d["id"]
        return None

    def state(self):
        return self.call("GET", "/me/player")

    def play(self, device_id=None, context_uri=None, uris=None, offset=None, position_ms=None):
        body = {}
        if position_ms:
            body["position_ms"] = int(position_ms)
        if context_uri:
            body["context_uri"] = context_uri
        if uris:
            body["uris"] = uris
        if offset is not None:   # int position, or a track URI inside the context
            body["offset"] = {"uri": offset} if isinstance(offset, str) else {"position": offset}
        params = {"device_id": device_id} if device_id else None
        return self.call("PUT", "/me/player/play", params, body or None)

    def pause(self):
        return self.call("PUT", "/me/player/pause")

    def next(self):
        return self.call("POST", "/me/player/next")

    def previous(self):
        return self.call("POST", "/me/player/previous")

    def seek(self, ms):
        return self.call("PUT", "/me/player/seek", {"position_ms": int(ms)})

    def volume(self, pct):
        return self.call("PUT", "/me/player/volume", {"volume_percent": int(pct)})

    def queue(self):
        return self.call("GET", "/me/player/queue")

    def add_to_queue(self, uri):
        return self.call("POST", "/me/player/queue", {"uri": uri})

    def transfer(self, device_id, play=False):
        return self.call("PUT", "/me/player", body={"device_ids": [device_id], "play": play})

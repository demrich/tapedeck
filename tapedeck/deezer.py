"""Deezer's public catalog API (no key, no login): the music-graph data Spotify withholds from
development-mode apps. Used for similar artists, an artist's popular tracks and artist radio.
Results are names, matched back to Spotify tracks/artists by search before anything plays.
"""
import json
import urllib.parse
import urllib.request

API = "https://api.deezer.com"


def get(path, **params):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(f"Deezer: {data['error'].get('message', 'error')}")
    return data


def _norm(title):
    """Album titles compared loosely: case-folded, without "(Deluxe)"-style suffixes."""
    return title.split(" (")[0].split(" - ")[0].strip().casefold()


def find_artist(name, titles=None):
    """Deezer artist id for a Spotify artist name, or None.

    Names collide a lot (several "Chon"s, many "Victoria"s). With titles (album names known from
    Spotify), the match must share an album; without them, the best-known exact match wins.
    """
    hits = get("/search/artist", q=name, limit=10).get("data", [])
    exact = sorted((a for a in hits if a["name"].casefold() == name.casefold()),
                   key=lambda a: -a.get("nb_fan", 0))
    if titles is None:
        return (exact or hits or [{}])[0].get("id")
    want = {_norm(t) for t in titles}
    for a in exact[:3]:
        have = {_norm(x["title"]) for x in get(f"/artist/{a['id']}/albums", limit=100).get("data", [])}
        if want & have:
            return a["id"]
    return None


def artist_of_track(title, artist):
    """Deezer artist id via one of their tracks: the surest match when radio starts from a song."""
    # (Deezer's artist:"" filter returns nothing these days, so search plainly and check the name)
    for t in get("/search", q=f"{artist} {title}", limit=5).get("data", []):
        if t["artist"]["name"].casefold() == artist.casefold():
            return t["artist"]["id"]
    return None


def related(did, limit=12):
    return [a["name"] for a in get(f"/artist/{did}/related", limit=limit).get("data", [])]


def top(did, limit=5):
    return [(t["title"], t["artist"]["name"]) for t in get(f"/artist/{did}/top", limit=limit).get("data", [])]


def radio(did):
    """About 25 tracks in the style of the artist; a fresh mix on every call."""
    return [(t["title"], t["artist"]["name"]) for t in get(f"/artist/{did}/radio").get("data", [])]

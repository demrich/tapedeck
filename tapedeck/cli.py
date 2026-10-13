"""Milestone-1 test harness: python3 -m tapedeck.cli <command> [args]"""
import os
import sys

from . import spotify


def main(argv):
    cmd, args = (argv[0], argv[1:]) if argv else ("help", [])
    if cmd == "setup":
        os.makedirs(spotify.CONFIG_DIR, exist_ok=True)
        with open(spotify.CLIENT_FILE, "w") as f:
            f.write(args[0].strip() + "\n")
        print("Client ID saved.")
        return
    if cmd == "login":
        spotify.login()
        print("INSERT CASSETTE: logged in as", spotify.Spotify().me()["display_name"])
        return
    sp = spotify.Spotify()
    if cmd == "devices":
        for d in sp.devices():
            print(f"{'*' if d['is_active'] else ' '} {d['name']:<20} {d['type']:<10} {d['id']}")
    elif cmd == "search":
        for t in sp.search(" ".join(args))["tracks"]["items"]:
            print(f"{t['uri']}  {t['name']} - {t['artists'][0]['name']}")
    elif cmd == "playlists":
        for p in sp.playlists()["items"]:
            print(f"{p['uri']}  {p['name']}")
    elif cmd == "play":
        dev = sp.device_id()
        if not dev:
            sys.exit("TAPEDECK device not found. Is librespot running?")
        uri = args[0] if args else None
        if uri and ":track:" in uri:
            sp.play(dev, uris=[uri])
        else:
            sp.play(dev, context_uri=uri)
        print("PLAY")
    elif cmd in ("pause", "next", "previous"):
        getattr(sp, cmd)()
        print(cmd.upper())
    elif cmd == "now":
        s = sp.state()
        if not s or not s.get("item"):
            print("NO CASSETTE")
        else:
            i = s["item"]
            print(f"{'▶' if s['is_playing'] else '⏸'} {i['name']} - {i['artists'][0]['name']} "
                  f"{s['progress_ms'] // 60000}:{s['progress_ms'] // 1000 % 60:02d} on {s['device']['name']}")
    else:
        print(__doc__, "\ncommands: setup <client_id> | login | devices | search <q> | playlists | "
              "play [uri] | pause | next | previous | now")


if __name__ == "__main__":
    main(sys.argv[1:])

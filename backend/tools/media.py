import base64
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from urllib.parse import quote_plus

from dotenv import load_dotenv

from tools.mac_core import click_element_by_label, read_accessibility_tree

load_dotenv()


VIDEO_SERVICES = {
    "netflix": {
        "app": "Google Chrome",
        "search_url": "https://www.netflix.com/search?q={query}",
        "home_url": "https://www.netflix.com",
    },
}

MUSIC_SERVICES = {
    "spotify": {
        "app": "Spotify",
        "search_uri": "spotify:search:{query}",
    },
}


def _run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _osascript(script: str, check: bool = False) -> subprocess.CompletedProcess:
    return _run(["osascript", "-e", script], check=check)


def _apple_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _activate(app_name: str) -> None:
    _osascript(f'tell application "{_apple_string(app_name)}" to activate')


def _open_chrome_url(url: str) -> dict:
    escaped_url = _apple_string(url)
    script = f"""
    tell application "Google Chrome"
        make new window
        set URL of active tab of front window to "{escaped_url}"
    end tell
    """
    try:
        _osascript(script, check=True)
        return {"status": "success", "message": f"Opened {url} in a new window"}
    except Exception as e:
        fallback = _run(["open", "-na", "Google Chrome", "--args", "--new-window", url])
        if fallback.returncode == 0:
            return {"status": "success", "message": f"Opened {url} in a new window"}
        return {"status": "error", "message": str(e)}


def _wait_for_label(label: str, app_name: str, timeout: float = 8.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            result = json.loads(read_accessibility_tree(app_name))
            if result.get("status") == "success":
                for node in result.get("tree", []):
                    if label.lower() in (node.get("label") or "").lower():
                        return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def _click_first(labels: list[str], app_name: str) -> bool:
    for label in labels:
        try:
            result = json.loads(click_element_by_label(label, app_name))
            if result.get("status") == "success":
                return True
        except Exception:
            pass
    return False


# Spotify Web API — used to resolve a song name to an exact track URI, which
# the desktop app can then play reliably. Client-credentials flow (no user
# login): cache the bearer token until it expires.
_SPOTIFY_TOKEN: dict = {"value": None, "expires_at": 0.0}


def _spotify_token() -> str | None:
    if _SPOTIFY_TOKEN["value"] and time.time() < _SPOTIFY_TOKEN["expires_at"]:
        return _SPOTIFY_TOKEN["value"]

    cid = os.getenv("SPOTIFY_CLIENT_ID")
    secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not cid or not secret:
        return None

    try:
        auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
        req = urllib.request.Request(
            "https://accounts.spotify.com/api/token",
            data=data,
            headers={"Authorization": f"Basic {auth}"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read())
        _SPOTIFY_TOKEN["value"] = payload["access_token"]
        # Refresh a minute early to avoid edge-of-expiry failures.
        _SPOTIFY_TOKEN["expires_at"] = time.time() + payload.get("expires_in", 3600) - 60
        return _SPOTIFY_TOKEN["value"]
    except Exception:
        return None


def _spotify_search_track(title: str) -> dict | None:
    """Returns {'uri', 'name', 'artist'} for the top track match, or None."""
    token = _spotify_token()
    if not token:
        return None
    try:
        q = urllib.parse.urlencode({"q": title, "type": "track", "limit": 1})
        req = urllib.request.Request(
            f"https://api.spotify.com/v1/search?{q}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            items = json.loads(resp.read())["tracks"]["items"]
        if not items:
            return None
        t = items[0]
        return {
            "uri": t["uri"],
            "name": t["name"],
            "artist": t["artists"][0]["name"] if t["artists"] else "",
        }
    except Exception:
        return None


def _play_spotify(title: str) -> dict:
    # Preferred path: resolve the exact track via the Web API and play it.
    track = _spotify_search_track(title)
    if track:
        _activate("Spotify")
        time.sleep(0.3)
        play_script = (
            f'tell application "Spotify" to play track "{_apple_string(track["uri"])}"'
        )
        res = _osascript(play_script)
        if res.returncode == 0:
            artist = f" by {track['artist']}" if track["artist"] else ""
            return {
                "status": "success",
                "message": f"Now playing '{track['name']}'{artist} on Spotify.",
            }

    # Fallback: no API creds (or play failed) — open search and nudge the top result.
    query = quote_plus(title)
    uri = MUSIC_SERVICES["spotify"]["search_uri"].format(query=query)
    opened = _run(["open", uri])
    if opened.returncode != 0:
        return {
            "status": "error",
            "message": opened.stderr.strip() or "Could not open Spotify search.",
        }

    time.sleep(1.2)
    _activate("Spotify")
    time.sleep(0.3)
    enter_script = """
    tell application "System Events"
        tell process "Spotify"
            key code 36
        end tell
    end tell
    """
    res = _osascript(enter_script)
    if res.returncode != 0:
        _osascript('tell application "Spotify" to play')

    return {
        "status": "success",
        "message": f"Opened Spotify search for '{title}'. Hit play if it didn't start.",
    }


def _play_netflix(title: str) -> dict:
    encoded = quote_plus(title)
    url = VIDEO_SERVICES["netflix"]["search_url"].format(query=encoded)
    nav = _open_chrome_url(url)
    if nav.get("status") != "success":
        return nav

    _activate("Google Chrome")
    found_title = _wait_for_label(title, "Google Chrome", timeout=10.0)

    clicked_card = _click_first(
        [
            f"Play {title}",
            title,
            "Play",
        ],
        "Google Chrome",
    )

    if clicked_card:
        time.sleep(1.0)
        _click_first(["Play", "Resume", "Start Over"], "Google Chrome")
        return {
            "status": "success",
            "message": f"Opened Netflix and selected '{title}'.",
        }

    if found_title:
        return {
            "status": "success",
            "message": f"Opened Netflix search results for '{title}'. I could see it, but could not auto-click the card.",
        }

    return {
        "status": "success",
        "message": f"Opened Netflix search for '{title}'. You may need to choose a profile, sign in, or pick the title manually.",
    }


def play_media(title: str, service: str = "netflix") -> dict:
    """
    High-level media command for FRIDAY.

    This intentionally avoids making the LLM stitch together app opening, URL
    routing, search typing, and AX clicks. Each service gets a direct route first,
    then a small best-effort UI action where needed.
    """
    clean_title = (title or "").strip()
    clean_service = (service or "netflix").strip().lower()

    if not clean_title:
        return {"status": "error", "message": "Missing media title."}

    if clean_service in {"netflix", "netflix.com"}:
        return _play_netflix(clean_title)

    if clean_service in {"spotify", "music"}:
        return _play_spotify(clean_title)

    return {
        "status": "error",
        "message": f"Unsupported media service '{service}'. Supported: Netflix, Spotify.",
    }

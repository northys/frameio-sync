import json
import subprocess
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .config import read_json, write_json

PHOTOS_IMPORT = """
on run argv
    set albumName to item 1 of argv
    set imports to {}
    repeat with p in items 2 thru -1 of argv
        set end of imports to POSIX file (contents of p)
    end repeat
    with timeout of 900 seconds
        tell application "Photos"
            if not (exists album albumName) then make new album named albumName
            import imports into album albumName skip check duplicates true
        end tell
    end timeout
end run
"""


def apple_photos_import(paths: list[Path], album: str) -> None:
    """One call per group so Photos keeps a JPG+RAW pair as a single asset."""
    result = subprocess.run(
        ["osascript", "-e", PHOTOS_IMPORT, album, *map(str, paths)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        names = ", ".join(p.name for p in paths)
        raise RuntimeError(f"Photos import failed for {names}: {result.stderr.strip()}")


GOOGLE_SCOPES = ["https://www.googleapis.com/auth/photoslibrary.appendonly"]
GOOGLE_API = "https://photoslibrary.googleapis.com/v1"
GOOGLE_TOKENS = "google-tokens.json"
GOOGLE_ALBUM = "google-album.json"


def google_login(client_id: str, client_secret: str) -> None:
    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        GOOGLE_SCOPES,
    )
    credentials = flow.run_local_server(port=0)
    write_json(GOOGLE_TOKENS, json.loads(credentials.to_json()))


class GooglePhotos:
    def __init__(self, session, album_id: str):
        self.session = session
        self.album_id = album_id

    @classmethod
    def open(cls, album: str) -> "GooglePhotos":
        tokens = read_json(GOOGLE_TOKENS, None)
        if not tokens:
            raise SystemExit("not logged in to Google: run `frameio-sync login google`")
        session = AuthorizedSession(Credentials.from_authorized_user_info(tokens, GOOGLE_SCOPES))
        cached = read_json(GOOGLE_ALBUM, {})
        if cached.get("title") != album:
            response = session.post(f"{GOOGLE_API}/albums", json={"album": {"title": album}})
            response.raise_for_status()
            cached = {"title": album, "id": response.json()["id"]}
            write_json(GOOGLE_ALBUM, cached)
        return cls(session, cached["id"])

    def upload(self, path: Path, mime_type: str) -> None:
        with path.open("rb") as f:
            response = self.session.post(
                f"{GOOGLE_API}/uploads",
                data=f,
                headers={
                    "Content-Type": "application/octet-stream",
                    "X-Goog-Upload-Content-Type": mime_type,
                    "X-Goog-Upload-Protocol": "raw",
                },
            )
        response.raise_for_status()
        upload_token = response.text
        response = self.session.post(
            f"{GOOGLE_API}/mediaItems:batchCreate",
            json={
                "albumId": self.album_id,
                "newMediaItems": [
                    {"simpleMediaItem": {"fileName": path.name, "uploadToken": upload_token}}
                ],
            },
        )
        response.raise_for_status()
        status = response.json()["newMediaItemResults"][0]["status"]
        if status.get("code", 0) != 0:
            raise RuntimeError(f"Google Photos rejected {path.name}: {status}")

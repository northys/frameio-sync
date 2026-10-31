import secrets
import webbrowser
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from frameio import Frameio
from frameio.auth import SPAAuth

from .config import read_json, write_json

REDIRECT_URI = "http://localhost:17865/callback"
TOKENS = "frameio-tokens.json"


def _auth(client_id: str) -> SPAAuth:
    return SPAAuth(
        client_id=client_id,
        redirect_uri=REDIRECT_URI,
        on_token_refreshed=lambda tokens: write_json(TOKENS, tokens),
    )


def _wait_for_code(expected_state: str) -> str:
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            if query.get("state", [None])[0] != expected_state:
                self.send_error(400, "state mismatch")
                return
            if "error" in query:
                result["error"] = query["error"][0]
            else:
                result["code"] = query["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Logged in. You can close this tab.")

        def log_message(self, *args):
            pass

    with HTTPServer(("127.0.0.1", 17865), Handler) as server:
        while not result:
            server.handle_request()
    if "error" in result:
        raise SystemExit(f"Adobe sign-in failed: {result['error']}")
    return result["code"]


def login(client_id: str) -> None:
    auth = _auth(client_id)
    state = secrets.token_urlsafe(16)
    request = auth.get_authorization_url(state=state)
    print("Opening the browser for Adobe sign-in...")
    webbrowser.open(request.url)
    auth.exchange_code(code=_wait_for_code(state), code_verifier=request.code_verifier)
    write_json(TOKENS, auth.export_tokens())


def client(client_id: str) -> Frameio:
    tokens = read_json(TOKENS, None)
    if not tokens:
        raise SystemExit("not logged in to Frame.io: run `frameio-sync login frameio`")
    auth = _auth(client_id)
    auth.import_tokens(tokens)
    return Frameio(token=auth.get_token)


def new_files(
    client: Frameio, seen: set[str], projects: list[str] | None, listed: list | None = None
) -> Iterator[list]:
    """Yield groups of (file, download_url) for finished images not in seen.

    Files in one folder that share a name stem (DSCF0131.JPG + DSCF0131.RAF) form one group.
    Every file walked, image or not, is appended to listed as (account_id, file).
    """
    for account in client.accounts.index():
        for workspace in client.workspaces.index(account.id):
            for project in client.projects.index(account.id, workspace.id):
                if projects and project.name not in projects:
                    continue
                yield from _walk(client, account.id, project.root_folder_id, seen, listed)


# shortcut: full crawl of every folder each run, switch to file.ready webhooks
# when the account grows past the 100 folder listings per minute rate limit
def _walk(
    client: Frameio, account_id: str, folder_id: str, seen: set[str], listed: list | None
) -> Iterator[list]:
    files = []
    for asset in client.folders.index(account_id, folder_id, include="media_links.original"):
        if asset.type == "folder":
            yield from _walk(client, account_id, asset.id, seen, listed)
            continue
        file = asset.head_version if asset.type == "version_stack" else asset
        if file is not None and listed is not None:
            listed.append((account_id, file))
        if file is not None and (file.media_type or "").startswith("image/"):
            files.append(file)
    # Camera to Cloud re-uploads shots now and then; same name and size in a folder is one photo
    identities = {(f.name.lower(), f.file_size) for f in files if f.id in seen}
    groups: dict[str, list] = {}
    for file in files:
        identity = (file.name.lower(), file.file_size)
        if file.id in seen or file.status == "created" or identity in identities:
            continue
        identities.add(identity)
        if file.media_links is None:
            file = client.files.show(account_id, file.id, include="media_links.original").data
        original = file.media_links.original if file.media_links else None
        if original and original.download_url:
            groups.setdefault(Path(file.name).stem.lower(), []).append(
                (file, original.download_url)
            )
    yield from groups.values()


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with dest.open("wb") as f:
            for chunk in response.iter_content(1 << 20):
                f.write(chunk)
    return dest

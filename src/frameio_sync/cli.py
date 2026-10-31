import argparse
import re
import sys
import tempfile
import time
import traceback
from pathlib import Path

from frameio.auth import TokenExpiredError
from google.auth.exceptions import RefreshError

from . import sinks, source, web
from .config import load_config, read_json, write_json

SEEN = "seen.json"
SYNCED = "synced.json"
PRUNE_PER_RUN = 90
SINKS = ("google_photos", "immich")
INTERVAL = 300
PORT = 8080
FRAMEIO_EXPIRED = "Frame.io login expired: run `frameio-sync login frameio`"
GOOGLE_EXPIRED = "Google login expired: run `frameio-sync login google`"


def baseline(cfg: dict) -> None:
    client = source.client(cfg["frameio"]["client_id"])
    seen = set(read_json(SEEN, []))
    for group in source.new_files(client, seen, cfg["frameio"].get("projects")):
        for file, _ in group:
            print("marking as seen:", file.name)
            seen.add(file.id)
    write_json(SEEN, sorted(seen))


def sync(cfg: dict, status: web.Status) -> None:
    if not any(name in cfg for name in SINKS):
        raise SystemExit(f"no target configured: add one of {SINKS} to config.toml")
    status.begin()
    client = source.client(cfg["frameio"]["client_id"])
    uploaders = []
    if "google_photos" in cfg:
        uploaders.append(sinks.GooglePhotos.open(cfg["google_photos"]["album"]))
    if "immich" in cfg:
        uploaders.append(sinks.Immich.open(**cfg["immich"]))
    seen = set(read_json(SEEN, []))
    synced = set(read_json(SYNCED, []))
    listed = []
    groups = list(source.new_files(client, seen, cfg["frameio"].get("projects"), listed))
    status.queue = [_names(group) for group in groups]
    with tempfile.TemporaryDirectory() as tmp:
        for group in groups:
            names = _names(group)
            try:
                _sync_group(uploaders, group, Path(tmp))
            except RefreshError:
                raise
            except Exception as e:
                print("failed:", names, file=sys.stderr)
                traceback.print_exc()
                status.event("failed", names, _describe(e))
                continue
            seen.update(file.id for file, _ in group)
            synced.update(file.id for file, _ in group)
            write_json(SEEN, sorted(seen))
            write_json(SYNCED, sorted(synced))
            print("synced:", names, flush=True)
            status.event("synced", names)
    if "keep_gb" in cfg["frameio"]:
        prune(client, listed, synced, int(cfg["frameio"]["keep_gb"] * 1e9), status)


# shortcut: counts head versions only, older versions in a version stack also use storage
def prune(client, listed: list, synced: set[str], keep_bytes: int, status: web.Status) -> None:
    """Delete the oldest synced files until the walked files fit in keep_bytes."""
    total = sum(file.file_size or 0 for _, file in listed)
    deleted, freed = [], 0
    for account_id, file in sorted(listed, key=lambda item: item[1].created_at):
        if total - freed <= keep_bytes or len(deleted) == PRUNE_PER_RUN:
            break
        if file.id not in synced:
            continue
        client.files.delete(account_id, file.id)
        deleted.append(file.name)
        freed += file.file_size or 0
    if deleted:
        summary = f"{len(deleted)} files, {freed / 1e9:.2f} GB: {deleted[0]} to {deleted[-1]}"
        print("pruned:", summary, flush=True)
        status.event("pruned", summary)


def _names(group: list) -> str:
    return ", ".join(file.name for file, _ in group)


def run(cfg: dict) -> None:
    status = web.Status()
    web.serve(status, PORT)
    print(f"status page on http://localhost:{PORT}", flush=True)
    while True:
        try:
            sync(cfg, status)
        except TokenExpiredError:
            _issue(status, FRAMEIO_EXPIRED)
        except RefreshError:
            _issue(status, GOOGLE_EXPIRED)
        except SystemExit as e:
            _issue(status, str(e))
        except Exception as e:
            traceback.print_exc()
            _issue(status, _describe(e))
        finally:
            status.finish(INTERVAL)
        time.sleep(INTERVAL)


# Download links are presigned; the page must not show their query strings
def _describe(exc: BaseException) -> str:
    return re.sub(r"\?\S*", "?…", f"{type(exc).__name__}: {exc}")


def _issue(status: web.Status, message: str) -> None:
    print(message, file=sys.stderr, flush=True)
    status.event("issue", "", message)


def _sync_group(uploaders: list, group: list, tmp: Path) -> None:
    paths = [source.download(url, tmp / file.id / Path(file.name).name) for file, url in group]
    for uploader in uploaders:
        for (file, _), path in zip(group, paths, strict=True):
            uploader.upload(path, file.media_type)
    for path in paths:
        path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(prog="frameio-sync")
    commands = parser.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login", help="sign in to a service once")
    login.add_argument("service", choices=["frameio", "google"])
    commands.add_parser("baseline", help="mark everything currently in Frame.io as already synced")
    commands.add_parser("sync", help="download new photos and import them once")
    commands.add_parser("run", help="sync every 5 minutes and serve the status page on :8080")
    args = parser.parse_args()
    cfg = load_config()
    try:
        if args.command == "login" and args.service == "frameio":
            source.login(cfg["frameio"]["client_id"])
        elif args.command == "login":
            google = cfg["google_photos"]
            sinks.google_login(google["client_id"], google["client_secret"])
        elif args.command == "baseline":
            baseline(cfg)
        elif args.command == "run":
            run(cfg)
        else:
            sync(cfg, web.Status())
    except TokenExpiredError:
        raise SystemExit(FRAMEIO_EXPIRED) from None
    except RefreshError:
        raise SystemExit(GOOGLE_EXPIRED) from None

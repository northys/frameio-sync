import argparse
import sys
import tempfile
import traceback
from pathlib import Path

from frameio.auth import TokenExpiredError
from google.auth.exceptions import RefreshError

from . import sinks, source
from .config import load_config, read_json, write_json

SEEN = "seen.json"
SINKS = ("apple_photos", "google_photos", "immich")


def baseline(cfg: dict) -> None:
    client = source.client(cfg["frameio"]["client_id"])
    seen = set(read_json(SEEN, []))
    for group in source.new_files(client, seen, cfg["frameio"].get("projects")):
        for file, _ in group:
            print("marking as seen:", file.name)
            seen.add(file.id)
    write_json(SEEN, sorted(seen))


def sync(cfg: dict) -> None:
    if not any(name in cfg for name in SINKS):
        raise SystemExit(f"no target configured: add one of {SINKS} to config.toml")
    client = source.client(cfg["frameio"]["client_id"])
    uploaders = []
    if "google_photos" in cfg:
        uploaders.append(sinks.GooglePhotos.open(cfg["google_photos"]["album"]))
    if "immich" in cfg:
        uploaders.append(sinks.Immich.open(**cfg["immich"]))
    seen = set(read_json(SEEN, []))
    with tempfile.TemporaryDirectory() as tmp:
        for group in source.new_files(client, seen, cfg["frameio"].get("projects")):
            names = ", ".join(file.name for file, _ in group)
            try:
                _sync_group(cfg, uploaders, group, Path(tmp))
            except RefreshError:
                raise
            except Exception:
                print("failed:", names, file=sys.stderr)
                traceback.print_exc()
                continue
            seen.update(file.id for file, _ in group)
            write_json(SEEN, sorted(seen))
            print("synced:", names, flush=True)


def _sync_group(cfg: dict, uploaders: list, group: list, tmp: Path) -> None:
    paths = [source.download(url, tmp / file.id / Path(file.name).name) for file, url in group]
    if "apple_photos" in cfg:
        sinks.apple_photos_import(paths, cfg["apple_photos"]["album"])
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
    commands.add_parser("sync", help="download new photos and import them")
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
        else:
            sync(cfg)
    except TokenExpiredError:
        raise SystemExit("Frame.io login expired: run `frameio-sync login frameio`") from None
    except RefreshError:
        raise SystemExit("Google login expired: run `frameio-sync login google`") from None

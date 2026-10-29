from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from frameio_sync import cli, sinks, source


def _file(
    id,
    name,
    media_type="image/jpeg",
    url="https://cdn/x",
    type="file",
    media_links=...,
    size=1,
    status="transcoded",
):
    if media_links is ...:
        media_links = NS(original=NS(download_url=url))
    return NS(
        type=type,
        id=id,
        name=name,
        media_type=media_type,
        media_links=media_links,
        file_size=size,
        status=status,
    )


class FakeClient:
    def __init__(self, tree):
        self.tree = tree
        self.accounts = NS(index=lambda: [NS(id="acc")])
        self.workspaces = NS(index=lambda account_id: [NS(id="ws")])
        self.projects = NS(
            index=lambda account_id, workspace_id: [
                NS(name="Wedding", root_folder_id="root"),
                NS(name="Other", root_folder_id="other-root"),
            ]
        )
        self.folders = NS(index=lambda account_id, folder_id, include: tree[folder_id])
        self.files = NS(
            show=lambda account_id, file_id, include: NS(data=_file(file_id, "shown.jpg"))
        )


def test_new_files_walks_folders_filters_and_pairs_by_stem():
    tree = {
        "root": [
            _file("seen", "seen.jpg"),
            _file("seen-reupload", "seen.jpg"),
            _file("jpg", "DSCF0131.JPG"),
            _file("raf", "DSCF0131.RAF", media_type="image/x-fujifilm-raf", url="https://cdn/raf"),
            _file("reupload", "DSCF0131.JPG"),
            _file("other-size", "DSCF0131.JPG", size=2),
            _file("clip", "clip.mov", media_type="video/quicktime"),
            _file("pending", "pending.jpg", media_type=None),
            _file("uploading", "DSCF0338.RAF", media_type="image/x-fujifilm-raf", status="created"),
            _file("nolink", "nolink.jpg", media_links=None),
            NS(type="folder", id="sub"),
            NS(type="version_stack", id="stack", head_version=_file("v2", "v2.jpg")),
        ],
        "sub": [_file("deep", "deep.jpg", url="https://cdn/deep")],
        "other-root": [_file("skipped-project", "x.jpg")],
    }
    groups = list(source.new_files(FakeClient(tree), {"seen"}, ["Wedding"]))
    assert [[(f.id, url) for f, url in g] for g in groups] == [
        [("deep", "https://cdn/deep")],
        [("jpg", "https://cdn/x"), ("raf", "https://cdn/raf"), ("other-size", "https://cdn/x")],
        [("nolink", "https://cdn/x")],
        [("v2", "https://cdn/x")],
    ]


def test_new_files_without_project_filter_covers_all_projects():
    tree = {"root": [_file("a", "a.jpg")], "other-root": [_file("b", "b.jpg")]}
    groups = source.new_files(FakeClient(tree), set(), None)
    assert [f.id for g in groups for f, _ in g] == ["a", "b"]


class FakeUploader:
    def __init__(self):
        self.uploaded = []

    def upload(self, path, mime_type):
        if path.name == "bad.jpg":
            raise RuntimeError("boom")
        self.uploaded.append(path.name)


def _run_sync(monkeypatch, tree, uploader, saved):
    dests = []

    def download(url, dest):
        dests.append(dest)
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"jpeg")
        return dest

    monkeypatch.setattr(cli.source, "client", lambda client_id: FakeClient(tree))
    monkeypatch.setattr(cli.source, "download", download)
    monkeypatch.setattr(cli.sinks.Immich, "open", lambda **kwargs: uploader)
    monkeypatch.setattr(cli, "read_json", lambda name, default: [])
    monkeypatch.setattr(cli, "write_json", lambda name, data: saved.update({name: data}))
    cli.sync({"frameio": {"client_id": "c"}, "immich": {}})
    return dests


def test_sync_continues_after_a_failed_group(monkeypatch):
    tree = {"root": [_file("bad", "bad.jpg"), _file("good", "good.jpg")], "other-root": []}
    uploader, saved = FakeUploader(), {}
    _run_sync(monkeypatch, tree, uploader, saved)
    assert uploader.uploaded == ["good.jpg"]
    assert saved == {"seen.json": ["good"]}


def test_sync_keeps_downloads_inside_the_temp_dir(monkeypatch):
    tree = {"root": [_file("evil", "../../escape.jpg")], "other-root": []}
    dests = _run_sync(monkeypatch, tree, FakeUploader(), {})
    assert [(d.parent.name, d.name) for d in dests] == [("evil", "escape.jpg")]


def test_sync_refuses_to_run_without_a_target():
    with pytest.raises(SystemExit, match="no target configured"):
        cli.sync({"frameio": {"client_id": "c"}})


class FakeSession:
    def __init__(self, status):
        self.status = status
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/uploads"):
            return NS(raise_for_status=lambda: None, text="tok")
        return NS(
            raise_for_status=lambda: None,
            json=lambda: {"newMediaItemResults": [{"status": self.status}]},
        )


def test_google_upload_sends_token_to_album(tmp_path: Path):
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"jpeg")
    session = FakeSession({"message": "Success"})
    sinks.GooglePhotos(session, "album-1").upload(photo, "image/jpeg")
    create = session.calls[1][1]["json"]
    assert create["albumId"] == "album-1"
    item = create["newMediaItems"][0]["simpleMediaItem"]
    assert item == {"fileName": "p.jpg", "uploadToken": "tok"}


def test_google_upload_raises_on_rejected_item(tmp_path: Path):
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"jpeg")
    session = FakeSession({"code": 3, "message": "bad"})
    try:
        sinks.GooglePhotos(session, "album-1").upload(photo, "image/jpeg")
    except RuntimeError as e:
        assert "p.jpg" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


class FakeImmichSession:
    def __init__(self, album_result):
        self.album_result = album_result
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return NS(raise_for_status=lambda: None, json=lambda: {"id": "asset-1"})

    def put(self, url, **kwargs):
        self.calls.append(("PUT", url, kwargs))
        return NS(raise_for_status=lambda: None, json=lambda: [self.album_result])


def test_immich_upload_adds_asset_to_album(tmp_path: Path):
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"jpeg")
    session = FakeImmichSession({"id": "asset-1", "success": False, "error": "duplicate"})
    sinks.Immich(session, "https://immich/api", "album-1").upload(photo, "image/jpeg")
    (_, upload_url, upload), (_, album_url, album) = session.calls
    assert upload_url == "https://immich/api/assets"
    assert upload["data"]["deviceAssetId"] == "p.jpg-4"
    assert upload["files"]["assetData"][0] == "p.jpg"
    assert album_url == "https://immich/api/albums/album-1/assets"
    assert album["json"] == {"ids": ["asset-1"]}


def test_immich_upload_raises_when_album_add_fails(tmp_path: Path):
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"jpeg")
    session = FakeImmichSession({"id": "asset-1", "success": False, "error": "no_permission"})
    with pytest.raises(RuntimeError, match="p.jpg"):
        sinks.Immich(session, "https://immich/api", "album-1").upload(photo, "image/jpeg")

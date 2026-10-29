# frameio-sync

Copies new photos from [Frame.io](https://frame.io) into Google Photos or
[Immich](https://immich.app), a few minutes after they land.

Made for Camera to Cloud: the camera uploads to Frame.io, and this tool puts every finished
shot into your own photo library without you touching a file. It talks to the Frame.io V4 API.

## What it does

- Every run lists the folders of the synced projects and downloads each image it has not
  seen before. Videos are skipped.
- A JPG and a RAW with the same name in one folder (`DSCF0131.JPG` + `DSCF0131.RAF`) are
  handled as one shot: both go to every target, or neither.
- A file that is still uploading is left for the next run. A re-upload of a shot with the
  same name and size in the same folder counts as the same photo.
- If a shot fails to upload, the run logs the error and retries it next time; the other
  shots are not held back.
- State lives in `~/Library/Application Support/frameio-sync/`: the OAuth tokens, the
  Google album id and `seen.json` with the ids of synced files.

## Requirements

- Python 3.13 and [uv](https://docs.astral.sh/uv/).
- A Frame.io V4 account (Adobe login) and a credential in the
  [Adobe Developer Console](https://developer.adobe.com/console): add the Frame.io API to a
  project, pick the OAuth Single-Page App type (PKCE, no client secret) and register
  `http://localhost:17865/callback` as a redirect URI.
- For Google Photos: a Google Cloud project with the Photos Library API enabled, an OAuth
  desktop client, and the `photoslibrary.appendonly` scope on its consent screen.
- For Immich: an API key (Account Settings > API Keys) with the `asset.upload`,
  `album.read`, `album.create` and `albumAsset.create` permissions.

## Setup

1. Clone and install:

   ```sh
   git clone https://github.com/northys/frameio-sync.git
   cd frameio-sync
   uv sync
   ```

2. Write `~/Library/Application Support/frameio-sync/config.toml`. Keep the target
   sections you use; at least one is required.

   ```toml
   [frameio]
   client_id = "<Adobe Developer Console client id>"
   # projects = ["Only this project"]   # omit to sync every project in every workspace

   [google_photos]
   client_id = "<Google Cloud OAuth desktop client id>"
   client_secret = "<its client secret>"
   album = "Frame.io"

   [immich]
   url = "https://immich.example.com"
   api_key = "<Immich API key>"
   album = "Frame.io"
   ```

3. Sign in to Frame.io, and to Google if you use Google Photos. Each opens a browser tab
   and stores a refresh token:

   ```sh
   uv run frameio-sync login frameio
   uv run frameio-sync login google
   ```

4. If Frame.io already holds photos you do not want synced, mark them as seen:

   ```sh
   uv run frameio-sync baseline
   ```

5. Run once by hand, then install the launchd job that runs `sync` every 5 minutes. Edit
   the paths in the plist if the checkout or your home directory differ:

   ```sh
   uv run frameio-sync sync
   cp launchd/com.northys.frameio-sync.plist ~/Library/LaunchAgents/
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.northys.frameio-sync.plist
   ```

## Troubleshooting

Logs go to `~/Library/Logs/frameio-sync.log`.

- `Frame.io login expired` or `Google login expired`: run the named `login` command again.
- Large accounts: every run lists every folder of the synced projects. Set `projects` in
  the config to keep the run short and within the Frame.io rate limit.

## Development

```sh
uv run pytest
uv run ruff check
uv run ruff format
```

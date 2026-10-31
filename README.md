# frameio-sync

Copies new photos from [Frame.io](https://frame.io) into Google Photos or
[Immich](https://immich.app), a few minutes after they land.

Made for Camera to Cloud: the camera uploads to Frame.io, and this tool puts every finished
shot into your own photo library without you touching a file. It talks to the Frame.io V4 API
and runs as a Docker container that syncs every 5 minutes and serves a status page.

## What it does

- Every run lists the folders of the synced projects and downloads each image it has not
  seen before. Videos are skipped.
- A JPG and a RAW with the same name in one folder (`DSCF0131.JPG` + `DSCF0131.RAF`) are
  handled as one shot: both go to every target, or neither.
- A file that is still uploading is left for the next run. A re-upload of a shot with the
  same name and size in the same folder counts as the same photo.
- If a shot fails to upload, the run logs the error and retries it next time; the other
  shots are not held back.
- The status page (port 8787 on the host) shows the current run, the queue of shots
  waiting in it, the issues (failed shots with their error, expired logins) and the
  migrated shots. It keeps the last 300 events across restarts.
- With `keep_gb` set, each run deletes the oldest files from Frame.io until the synced
  projects hold no more than that, so the account fits a plan with little storage.
  `1.6` keeps a free 2 GB plan at 80%. Only files this tool has uploaded are deleted,
  never files that are still waiting or were skipped with `baseline`. A run deletes at
  most 90 files, to stay under the Frame.io limit of 100 deletes per minute.
- State lives in `~/.config/frameio-sync/` (or `$FRAMEIO_SYNC_STATE`): the config, the OAuth
  tokens, the Google album id, `seen.json` with the ids of handled files, `synced.json` with
  the ids of uploaded files and `events.json` behind the status page. The container mounts
  that directory as `/data`.

## Requirements

- Docker with Compose to run it. [uv](https://docs.astral.sh/uv/) on a machine with a
  browser for the one-time sign-in.
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

2. Write `~/.config/frameio-sync/config.toml`. Keep the target sections you use; at least
   one is required.

   ```toml
   [frameio]
   client_id = "<Adobe Developer Console client id>"
   # projects = ["Only this project"]   # omit to sync every project in every workspace
   # keep_gb = 1.6   # delete the oldest uploaded files once the projects hold more than this

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
   and stores a refresh token. On a headless server, sign in elsewhere and copy the state
   directory over:

   ```sh
   uv run frameio-sync login frameio
   uv run frameio-sync login google
   ```

4. If Frame.io already holds photos you do not want synced, mark them as seen:

   ```sh
   uv run frameio-sync baseline
   ```

5. Build and start the container, then open the status page at http://localhost:8787:

   ```sh
   docker compose up -d --build
   ```

## Troubleshooting

The status page lists every failure with its error. The same lines go to
`docker compose logs -f`.

- `Frame.io login expired` or `Google login expired`: run the named `login` command again
  on the host. The container picks up the new token on its next run.
- Do not run `sync` by hand while the container is running. Two runs at once upload the
  same shots twice and trip the Google Photos rate limit.
- Large accounts: every run lists every folder of the synced projects. Set `projects` in
  the config to keep the run short and within the Frame.io rate limit.

## Development

```sh
uv sync
uv run pytest
uv run ruff check
uv run ruff format
```

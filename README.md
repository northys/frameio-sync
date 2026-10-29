# frameio-sync

Polls Frame.io (V4 API) for new image files and imports each one into Apple Photos,
Google Photos and/or Immich. State and tokens live in `~/Library/Application Support/frameio-sync/`.

## Setup

1. Write `~/Library/Application Support/frameio-sync/config.toml`. Every target section is
   optional; keep the ones you use (at least one):

   ```toml
   [frameio]
   client_id = "<Adobe Developer Console OAuth client id>"
   # projects = ["Only this project"]   # omit to sync every project in every workspace

   [apple_photos]
   album = "Frame.io"

   [google_photos]
   client_id = "<Google Cloud OAuth desktop client id>"
   client_secret = "<its client secret>"
   album = "Frame.io"

   [immich]
   url = "https://immich.example.com"
   api_key = "<Immich API key from Account Settings>"
   album = "Frame.io"
   ```

   The Adobe credential must be an OAuth app with `http://localhost:17865/callback`
   as a redirect URI. The Google client needs the Photos Library API enabled and the
   `photoslibrary.appendonly` scope on its consent screen. The Immich key needs the
   `asset.upload`, `album.read`, `album.create` and `albumAsset.create` permissions.

2. Sign in once per OAuth service. Each opens a browser tab and stores a refresh token:

   ```sh
   uv run frameio-sync login frameio
   uv run frameio-sync login google      # only with [google_photos]
   ```

3. Decide what to do with files already in Frame.io. To skip them:

   ```sh
   uv run frameio-sync baseline
   ```

4. Run once by hand (with `[apple_photos]`, macOS asks for Photos automation permission
   the first time), then install the launchd job that runs every 5 minutes:

   ```sh
   uv run frameio-sync sync
   cp launchd/com.northys.frameio-sync.plist ~/Library/LaunchAgents/
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.northys.frameio-sync.plist
   ```

   The first launchd run asks for Photos automation permission again, this time for `uv`.
   Until it is granted the log shows `AppleEvent timed out. (-1712)`.

Logs go to `~/Library/Logs/frameio-sync.log`. When a refresh token expires the log says
which `login` command to run again.

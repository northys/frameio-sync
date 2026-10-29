# frameio-sync

Polls Frame.io (V4 API) for new image files and imports each one into Apple Photos
and Google Photos. State and tokens live in `~/Library/Application Support/frameio-sync/`.

## Setup

1. Write `~/Library/Application Support/frameio-sync/config.toml`:

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
   ```

   Drop the `[apple_photos]` or `[google_photos]` section to disable that target.
   The Adobe credential must be an OAuth app with `http://localhost:17865/callback`
   as a redirect URI. The Google client needs the Photos Library API enabled and the
   `photoslibrary.appendonly` scope on its consent screen.

2. Sign in once per service. Each opens a browser tab and stores a refresh token:

   ```sh
   uv run frameio-sync login frameio
   uv run frameio-sync login google
   ```

3. Decide what to do with files already in Frame.io. To skip them:

   ```sh
   uv run frameio-sync baseline
   ```

4. Run once by hand (macOS asks for Photos automation permission the first time),
   then install the launchd job that runs every 5 minutes:

   ```sh
   uv run frameio-sync sync
   cp launchd/com.northys.frameio-sync.plist ~/Library/LaunchAgents/
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.northys.frameio-sync.plist
   ```

   The first launchd run asks for Photos automation permission again, this time for `uv`.
   Until it is granted the log shows `AppleEvent timed out. (-1712)`.

Logs go to `~/Library/Logs/frameio-sync.log`. When a refresh token expires the log says
which `login` command to run again.

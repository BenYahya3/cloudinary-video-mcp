# gdrive-video-mcp

A local **stdio MCP server** that lets Claude (or any MCP client) upload videos
from a folder on your computer to **Google Drive** and return shareable links.

- Auth: **OAuth as you** (uploads go to your own Drive). One-time browser
  consent, refresh token cached locally.
- Scope: `https://www.googleapis.com/auth/drive.file` — the app can only see
  files it created. It cannot read the rest of your Drive.
- Tools exposed:
  - `list_videos(folder_path?, recursive?)`
  - `upload_video(file_path, name?, drive_folder_id?, make_public?)`
  - `upload_folder(folder_path?, drive_folder_id?, recursive?, make_public?)`
  - `find_drive_folder(name, parent_id?)`
  - `create_drive_folder(name, parent_id?)`
  - `whoami()`

## 1. Get Google OAuth credentials (one-time, ~3 minutes)

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or reuse one) and **enable the Google Drive API**:
   https://console.cloud.google.com/apis/library/drive.googleapis.com
3. Configure the OAuth consent screen:
   - User Type: **External**
   - App name: anything (e.g. `gdrive-video-mcp`)
   - Add your own Google account as a **Test user**
   - You can leave the app in "Testing" mode — no verification needed.
4. Create credentials:
   - APIs & Services → Credentials → **Create Credentials** → **OAuth client ID**
   - Application type: **Desktop app**
   - Download the JSON.
5. Save it as `~/.config/gdrive-video-mcp/credentials.json` (or set
   `GDRIVE_MCP_CLIENT_SECRETS` to wherever you put it).

## 2. Install the server

Recommended via [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/BenYahya3/gdrive-video-mcp.git
cd gdrive-video-mcp
uv sync
```

Or with pip:

```bash
pip install -e .
```

## 3. First-run authorization

Run the consent flow once. This opens a browser, you pick your Google account,
and a `token.json` is cached under `~/.config/gdrive-video-mcp/`.

```bash
uv run python -c "from gdrive_video_mcp.auth import drive_service; \
print(drive_service().about().get(fields='user').execute())"
```

After this completes, you'll never see the browser again unless you delete the
cached token or change the OAuth scopes.

## 4. Configure Claude Desktop

Open Claude Desktop's config file:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

Add the server (replace the path to the videos folder with yours):

```json
{
  "mcpServers": {
    "gdrive-video": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/to/gdrive-video-mcp",
        "run", "gdrive-video-mcp"
      ],
      "env": {
        "GDRIVE_MCP_VIDEO_DIR": "/absolute/path/to/your/videos",
        "GDRIVE_MCP_DRIVE_FOLDER_ID": ""
      }
    }
  }
}
```

Notes:
- `GDRIVE_MCP_VIDEO_DIR` is the default folder used when you don't pass
  `folder_path` to a tool. You can always override per-call.
- `GDRIVE_MCP_DRIVE_FOLDER_ID` is optional. If set, all uploads go into that
  Drive folder. Get the ID from the folder's URL:
  `https://drive.google.com/drive/folders/<THIS_IS_THE_ID>`.
  You can also call `create_drive_folder("My uploads")` from Claude and then
  paste the returned id back into your config.
- If `uv` is not on Claude's PATH (common on macOS), replace `"uv"` with the
  absolute path printed by `which uv`.

Restart Claude Desktop. You should see the `gdrive-video` server listed with
its tools available.

## 5. Use it from Claude

Prompts like these now work:

> "List the videos in my videos folder."
>
> "Upload `clip.mp4` to Drive and give me the link."
>
> "Upload every video in `~/Movies/screen-recordings` to my Drive folder
> 'Cowork videos' and return the links as a markdown list."

## Environment variables

| Variable | Purpose |
| --- | --- |
| `GDRIVE_MCP_VIDEO_DIR` | Default local folder to scan. |
| `GDRIVE_MCP_DRIVE_FOLDER_ID` | Default Drive folder ID to upload into. |
| `GDRIVE_MCP_CLIENT_SECRETS` | Path to the OAuth client JSON. Default: `~/.config/gdrive-video-mcp/credentials.json`. |
| `GDRIVE_MCP_TOKEN_PATH` | Path to the cached OAuth token. Default: `~/.config/gdrive-video-mcp/token.json`. |

## Supported video extensions

`.mp4 .mov .m4v .mkv .webm .avi .wmv .flv .mpeg .mpg .3gp .ts .mts .m2ts`

Files with other extensions can still be uploaded via `upload_video` — you'll
just get a `warning` field on the response.

## Security notes

- The `drive.file` scope means the server **cannot** read files it didn't
  create. Even if your Claude session asks it to, the API will refuse.
- `make_public=true` adds the `anyone with link` reader role. Pass
  `make_public=false` to keep uploads private.
- The cached `token.json` grants long-lived access to your Drive (for files
  this app created). Treat it like a credential — don't commit it.

## License

MIT

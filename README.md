# gdrive-video-mcp

A remote **MCP server** hosted on Fly.io that uploads videos to **Cloudinary**
and returns permanent CDN URLs. Designed to be added to Claude (Desktop or
claude.ai's MCP support) as a remote MCP URL.

> ℹ️ The project is named `gdrive-video-mcp` for historical reasons (the first
> draft used Google Drive). The current destination is **Cloudinary** — chosen
> for purpose-built video hosting, transforms, and a CDN.

## Architecture

```
┌──────────────┐    bearer-auth HTTPS    ┌────────────────────┐    Cloudinary API   ┌────────────┐
│  Claude      │ ───────────────────────►│ Fly MCP server     │ ───────────────────►│ Cloudinary │
│  (MCP host)  │      /mcp (POST/GET)    │ (Streamable HTTP)  │                     │   CDN      │
└──────────────┘                         └────────────────────┘                     └────────────┘
       ▲                                                                                   │
       │                                                                                   ▼
       │            (returns CDN URL: https://res.cloudinary.com/<cloud>/video/upload/...)
       └────────────────────────────────────────────────────────────────────────────────────
```

Local videos reach Cloudinary either:
- **Via the companion CLI** (`gdrive-video-mcp-upload /path/to/videos`) running on your machine.
- **Via Claude calling `upload_from_url`** with any public URL — Cloudinary fetches directly.

## Tools

| Tool | Purpose |
| --- | --- |
| `upload_from_url(url, public_id?, folder?, tags?)` | Upload a video by URL. Cloudinary fetches it. |
| `list_videos(folder?, tag?, max_results?, next_cursor?)` | List uploaded videos. |
| `get_video(public_id)` | Metadata + CDN URL + thumbnail URL. |
| `delete_video(public_id)` | Permanently delete. |
| `whoami()` | Cloud name + (when available) usage stats. |

Each upload response includes:
- `url` — the secure `https://res.cloudinary.com/...` CDN URL.
- `thumbnail_url` — auto-generated JPG poster from 2 seconds in.
- `public_id`, `format`, `duration`, `width`, `height`, `bytes`.

## Deploy to Fly.io

Requires the Fly CLI and a Fly account.

```bash
# 1. Clone
git clone https://github.com/BenYahya3/gdrive-video-mcp.git
cd gdrive-video-mcp

# 2. Launch (creates the app; doesn't deploy yet)
fly apps create gdrive-video-mcp

# 3. Set secrets — these stay encrypted on Fly, never in the repo.
fly secrets set \
  CLOUDINARY_URL="cloudinary://API_KEY:API_SECRET@CLOUD_NAME" \
  MCP_BEARER_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"

# 4. Deploy
fly deploy --remote-only

# 5. Get your URL
fly status
```

Your MCP endpoint will be at:

```
https://<your-app>.fly.dev/mcp
```

The bearer token printed by step 3 is what you'll paste into Claude.

## Connect from Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "gdrive-video": {
      "type": "http",
      "url": "https://<your-app>.fly.dev/mcp",
      "headers": {
        "Authorization": "Bearer <MCP_BEARER_TOKEN>"
      }
    }
  }
}
```

Restart Claude Desktop. The `gdrive-video` server should appear with all 5 tools.

## Upload videos from your local folder

```bash
# One-time install of the companion CLI:
pip install git+https://github.com/BenYahya3/gdrive-video-mcp.git

# Then point it at a folder (uses your own Cloudinary credentials, not the Fly server):
export CLOUDINARY_URL='cloudinary://API_KEY:API_SECRET@CLOUD_NAME'
gdrive-video-mcp-upload ~/Videos/cowork --folder cowork --tag claude
```

Each video is uploaded directly from your machine to Cloudinary; no Fly
round-trip. Once uploaded, ask Claude to `list_videos(folder="cowork")` to see them.

## Local development

```bash
uv sync
uv run pytest -q

# Run the HTTP server locally on :8080
export CLOUDINARY_URL='...'
export MCP_BEARER_TOKEN='dev-token'
uv run gdrive-video-mcp

# Or run as a stdio MCP for local Claude Desktop testing
uv run python -m gdrive_video_mcp.server
```

## Environment variables

| Variable | Purpose |
| --- | --- |
| `CLOUDINARY_URL` | `cloudinary://API_KEY:API_SECRET@CLOUD_NAME`. Required for any upload/list/delete operation. |
| `MCP_BEARER_TOKEN` | Shared secret required to call `/mcp`. If unset, the endpoint is open. |
| `PORT`, `HOST` | Bind address. Default `0.0.0.0:8080`. |
| `LOG_LEVEL` | uvicorn log level (`info` by default). |

## Security notes

- The MCP endpoint is **only as private as `MCP_BEARER_TOKEN`**. Anyone with
  that token can upload to (and delete from) your Cloudinary account.
  Rotate it via `fly secrets set MCP_BEARER_TOKEN=...` whenever you suspect leakage.
- `CLOUDINARY_URL` contains your API secret — never commit it. The server
  reads it only at request time from Fly secrets / your local env.
- The `delete_video` tool is destructive. Cloudinary deletions are permanent.

## License

MIT

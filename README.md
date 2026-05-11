# cloudinary-video-mcp

A remote **MCP server** hosted on Fly.io that uploads videos to **Cloudinary**
and returns permanent CDN URLs. Designed to be added to Claude (Claude Desktop
via static bearer auth, or claude.ai web via OAuth 2.1 Custom Connectors).

> ℹ️ The Python package itself is still called `gdrive_video_mcp` for historical
> reasons (the first draft used Google Drive). The destination is now Cloudinary.

## Architecture

```
┌──────────────┐   bearer / OAuth HTTPS   ┌────────────────────┐    Cloudinary API   ┌────────────┐
│  Claude      │ ────────────────────────►│ Fly MCP server     │ ───────────────────►│ Cloudinary │
│  (MCP host)  │   /mcp (POST/GET)        │ (Streamable HTTP)  │                     │   CDN      │
└──────────────┘                          └────────────────────┘                     └────────────┘
       ▲                                          │
       │                                          ▼
       │            (returns CDN URL: https://res.cloudinary.com/<cloud>/video/upload/...)
       └────────────────────────────────────────────────────────────────────────────────────
```

Local videos reach Cloudinary in one of three ways, picked by file size:

1. **`upload_from_url(url, ...)`** — Cloudinary fetches a public URL directly.
2. **`upload_video(file_data_base64, ...)`** — Claude passes the file bytes inline.
   Works for files up to a few MB (limited by Claude's tool-call context).
3. **`create_upload_link(filename, folder, ...)`** — for files too big to base64.
   Returns a one-time signed URL on the Fly server; the user opens it in their
   browser, drops the file in, and the server streams it to Cloudinary via
   `upload_large` (6MB chunks for files ≥20MB). Bounded only by your Cloudinary
   plan (free tier: 100MB).

## Tools

| Tool | Purpose |
| --- | --- |
| `upload_from_url(url, public_id?, folder?, tags?)` | Upload by URL. Cloudinary fetches it directly. |
| `upload_video(file_data_base64, filename?, ...)` | Upload from raw bytes (small files). |
| `create_upload_link(filename, folder?, tags?, public_id?, ttl_seconds?)` | One-time browser upload URL (large files). |
| `list_videos(folder?, tag?, max_results?, next_cursor?)` | List uploaded videos. |
| `get_video(public_id)` | Metadata + CDN URL + thumbnail URL. |
| `delete_video(public_id)` | Permanently delete. |
| `whoami()` | Cloud name + (when available) usage stats. |

Each upload response includes:
- `url` — the secure `https://res.cloudinary.com/...` CDN URL.
- `thumbnail_url` — auto-generated JPG poster from 2 seconds in.
- `public_id`, `format`, `duration`, `width`, `height`, `bytes`.

## Auth

The `/mcp` endpoint accepts **either**:

- A static `MCP_BEARER_TOKEN` (Claude Desktop / curl), **or**
- An OAuth-issued access token. Full OAuth 2.1 + RFC 7591 Dynamic Client
  Registration + RFC 8414 discovery + PKCE — required by claude.ai web Custom
  Connectors. Tokens are HMAC-signed with `MCP_BEARER_TOKEN` as the key
  (stateless, no database).

The browser upload page at `/upload/<token>` uses the signed token itself as
authentication — no bearer required — so the user can open the link directly
from their browser.

## Deploy to Fly.io

Requires the Fly CLI and a Fly account.

```bash
# 1. Clone
git clone https://github.com/BenYahya3/cloudinary-video-mcp.git
cd cloudinary-video-mcp

# 2. Launch (creates the app; doesn't deploy yet)
fly apps create cloudinary-video-mcp

# 3. Set secrets — these stay encrypted on Fly, never in the repo.
fly secrets set \
  CLOUDINARY_URL="cloudinary://API_KEY:API_SECRET@CLOUD_NAME" \
  MCP_BEARER_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  MCP_ALLOWED_HOSTS="cloudinary-video-mcp.fly.dev" \
  PUBLIC_BASE_URL="https://cloudinary-video-mcp.fly.dev"

# 4. Deploy
fly deploy --remote-only

# 5. Get your URL
fly status
```

Your MCP endpoint will be at:

```
https://<your-app>.fly.dev/mcp
```

The bearer token printed by step 3 is what you'll paste into Claude (or into
the OAuth consent page for claude.ai web).

## Connect from Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cloudinary-video": {
      "type": "http",
      "url": "https://<your-app>.fly.dev/mcp",
      "headers": {
        "Authorization": "Bearer <MCP_BEARER_TOKEN>"
      }
    }
  }
}
```

Restart Claude Desktop. The server should appear with all tools.

For older Claude Desktop builds that don't yet support remote HTTP MCPs:

```json
{
  "mcpServers": {
    "cloudinary-video": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote",
        "https://<your-app>.fly.dev/mcp",
        "--header", "Authorization: Bearer <MCP_BEARER_TOKEN>"
      ]
    }
  }
}
```

## Connect from claude.ai web

Settings → Connectors → Add custom connector → URL: `https://<your-app>.fly.dev/mcp`.
Claude will open a consent page; paste your `MCP_BEARER_TOKEN` once and click
Authorize. From then on, Claude uses its own OAuth-issued access token (30-day TTL).

## Upload videos from your local folder

```bash
# One-time install of the companion CLI:
pip install git+https://github.com/BenYahya3/cloudinary-video-mcp.git

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
| `MCP_BEARER_TOKEN` | Shared secret required to call `/mcp`. Also the HMAC key for OAuth and upload-link tokens. If unset, the endpoint is open. |
| `MCP_ALLOWED_HOSTS` | Comma-separated list of Host header values to allow (DNS-rebinding protection). Use `*` to disable. |
| `PUBLIC_BASE_URL` | Public origin (e.g. `https://cloudinary-video-mcp.fly.dev`). Used to build upload links. |
| `PORT`, `HOST` | Bind address. Default `0.0.0.0:8080`. |
| `LOG_LEVEL` | uvicorn log level (`info` by default). |

## Security notes

- The MCP endpoint is **only as private as `MCP_BEARER_TOKEN`**. Anyone with
  that token can upload to (and delete from) your Cloudinary account.
  Rotate it via `fly secrets set MCP_BEARER_TOKEN=...` whenever you suspect leakage.
  Rotating invalidates every issued OAuth access token AND every outstanding upload
  link simultaneously (they're all HMAC-signed with the bearer as the key).
- `CLOUDINARY_URL` contains your API secret — never commit it. The server
  reads it only at request time from Fly secrets / your local env.
- The `delete_video` tool is destructive. Cloudinary deletions are permanent.

## License

MIT

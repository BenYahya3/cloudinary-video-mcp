"""One-time browser-based upload links.

Lets Claude hand the user a URL to upload a large file directly:
  - GET  /upload/<token>        → drag-and-drop HTML form
  - POST /upload/<token>        → multipart receive, stream-to-disk, push to Cloudinary
  - GET  /upload/<token>/status → JSON {ready, url?} so Claude can poll

Tokens are HMAC-signed (no DB) with MCP_BEARER_TOKEN as the key — encoding
the desired filename, folder, tags, public_id, and expiry.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import tempfile
import time
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from gdrive_video_mcp.cloudinary_client import upload_file_stream

DEFAULT_TTL_SECONDS = 60 * 60  # 1 hour
MAX_TTL_SECONDS = 24 * 60 * 60  # 24 hours
_DEFAULT_FOLDER_SLUG = re.compile(r"[^A-Za-z0-9._-]+")


def _signing_key() -> bytes:
    """Sign tokens with MCP_BEARER_TOKEN. Falls back to a per-process random key in dev."""
    tok = os.environ.get("MCP_BEARER_TOKEN", "").strip()
    if not tok:
        return os.environ.setdefault("_GVMCP_UPLOAD_DEV_KEY", secrets.token_urlsafe(32)).encode()
    return tok.encode()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def sign_token(payload: dict[str, Any]) -> str:
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64url_encode(hmac.new(_signing_key(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str) -> dict[str, Any] | None:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = _b64url_encode(hmac.new(_signing_key(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64url_decode(body))
    except Exception:  # noqa: BLE001
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


def _slugify_stem(name: str) -> str:
    stem = os.path.splitext(os.path.basename(name))[0]
    cleaned = _DEFAULT_FOLDER_SLUG.sub("-", stem).strip("-_.")
    return cleaned or "video"


def create_upload_link(
    *,
    base_url: str,
    filename: str = "",
    folder: str | None = None,
    tags: list[str] | None = None,
    public_id: str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    """Build a signed upload URL. Returns a dict with `upload_url`, `expires_at`, etc."""
    ttl = max(60, min(int(ttl_seconds or DEFAULT_TTL_SECONDS), MAX_TTL_SECONDS))
    exp = int(time.time()) + ttl

    resolved_public_id = (public_id or _slugify_stem(filename or "video")).strip()

    payload = {
        "type": "ul",
        "iat": int(time.time()),
        "exp": exp,
        "filename": filename or "",
        "folder": folder or "",
        "tags": tags or [],
        "public_id": resolved_public_id,
        "jti": secrets.token_urlsafe(8),
    }
    token = sign_token(payload)
    upload_url = f"{base_url.rstrip('/')}/upload/{token}"
    return {
        "upload_url": upload_url,
        "public_id": resolved_public_id,
        "folder": folder or "",
        "expires_at": exp,
        "expires_in_seconds": ttl,
        "instructions": (
            "Open `upload_url` in a browser, drop the video file, click Upload. "
            "When done, ask Claude to poll for the result — it will appear in "
            "Cloudinary at folder/public_id."
        ),
    }


_HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Upload to Cloudinary</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: dark; }
  body { font: 15px/1.5 -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif;
         background: #0b0d12; color: #e6e8eb; margin: 0; min-height: 100vh;
         display: flex; align-items: center; justify-content: center; padding: 24px; }
  .card { background: #14171d; border: 1px solid #232732; border-radius: 14px;
          padding: 32px; width: 540px; max-width: 100%; box-shadow: 0 30px 80px rgba(0,0,0,.4); }
  h1 { font-size: 20px; margin: 0 0 8px; }
  .sub { color: #aab1bd; margin: 0 0 24px; font-size: 14px; }
  .meta { color: #7a8090; font-size: 12px; margin-bottom: 18px; }
  .meta code { background: #1c2030; padding: 2px 6px; border-radius: 4px; color: #cbd1da; }
  .drop { border: 2px dashed #2a3040; background: #0d1017; border-radius: 12px;
          padding: 28px 18px; text-align: center; cursor: pointer; transition: .12s; }
  .drop:hover, .drop.drag { border-color: #4f46e5; background: #11142a; }
  .drop input { display: none; }
  .drop .label { font-weight: 600; color: #cbd1da; }
  .drop .hint { color: #6b7280; font-size: 12px; margin-top: 6px; }
  .selected { margin-top: 14px; font-size: 14px; color: #e6e8eb; word-break: break-all; }
  .selected b { color: #a5b4fc; }
  button { margin-top: 18px; width: 100%; padding: 12px 16px; border-radius: 10px;
    background: #4f46e5; color: white; border: 0; font-weight: 600; cursor: pointer;
    font-size: 14px; }
  button:hover { background: #6366f1; }
  button:disabled { background: #2a2f44; cursor: not-allowed; opacity: .6; }
  .progress { margin-top: 14px; height: 6px; background: #1c2030;
    border-radius: 3px; overflow: hidden; display: none; }
  .progress.show { display: block; }
  .bar { height: 100%; width: 0%; background: linear-gradient(90deg, #4f46e5, #818cf8);
    transition: width .15s ease-out; }
  .status { margin-top: 12px; font-size: 13px; color: #aab1bd; min-height: 18px; }
  .ok { background: #10221b; border: 1px solid #1f3d2f; border-radius: 10px;
        padding: 14px; margin-top: 18px; word-break: break-all; }
  .ok b { color: #6ee7b7; }
  .err { color: #fca5a5; margin-top: 12px; font-size: 13px; }
  a.copy { color: #a5b4fc; text-decoration: none; font-size: 12px; margin-left: 6px; }
  a.copy:hover { text-decoration: underline; }
  pre { background: #0d1017; padding: 10px 12px; border-radius: 6px;
        font: 12px ui-monospace, SFMono-Regular, monospace; overflow: auto; margin: 8px 0 0;
        color: #cbd1da; }
</style>
</head>
<body>
<form id="f" class="card" enctype="multipart/form-data">
  <h1>Upload video to Cloudinary</h1>
  <p class="sub">This page accepts your video and forwards it straight to Cloudinary.</p>
  <div class="meta">
    Target: <code>__TARGET__</code> · expires in <code>__EXPIRES__</code>
  </div>
  <label class="drop" id="drop">
    <input type="file" id="file" name="file" accept="video/*">
    <div class="label">Drag a video here, or click to select</div>
    <div class="hint">Up to your Cloudinary plan limit (free tier: 100&nbsp;MB)</div>
  </label>
  <div class="selected" id="sel"></div>
  <button id="go" type="submit" disabled>Upload</button>
  <div class="progress" id="pwrap"><div class="bar" id="bar"></div></div>
  <div class="status" id="st"></div>
  <div id="result"></div>
</form>
<script>
  const f = document.getElementById('f');
  const file = document.getElementById('file');
  const drop = document.getElementById('drop');
  const sel = document.getElementById('sel');
  const go = document.getElementById('go');
  const bar = document.getElementById('bar');
  const pwrap = document.getElementById('pwrap');
  const st = document.getElementById('st');
  const result = document.getElementById('result');

  const fmt = (n) => {
    if (n < 1024) return n + ' B';
    if (n < 1024*1024) return (n/1024).toFixed(1) + ' KB';
    if (n < 1024*1024*1024) return (n/1024/1024).toFixed(1) + ' MB';
    return (n/1024/1024/1024).toFixed(2) + ' GB';
  };

  const pickFile = (file) => {
    sel.innerHTML = '<b>' + file.name + '</b> &nbsp;·&nbsp; ' + fmt(file.size);
    go.disabled = false;
  };

  file.addEventListener('change', () => { if (file.files[0]) pickFile(file.files[0]); });
  ['dragenter','dragover'].forEach(e => drop.addEventListener(e, ev => {
    ev.preventDefault(); drop.classList.add('drag');
  }));
  ['dragleave','drop'].forEach(e => drop.addEventListener(e, ev => {
    ev.preventDefault(); drop.classList.remove('drag');
  }));
  drop.addEventListener('drop', ev => {
    if (ev.dataTransfer.files[0]) {
      file.files = ev.dataTransfer.files;
      pickFile(ev.dataTransfer.files[0]);
    }
  });

  f.addEventListener('submit', ev => {
    ev.preventDefault();
    if (!file.files[0]) return;
    const fd = new FormData();
    fd.append('file', file.files[0]);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', window.location.pathname);
    xhr.upload.addEventListener('progress', e => {
      if (!e.lengthComputable) return;
      const pct = Math.round((e.loaded / e.total) * 100);
      pwrap.classList.add('show');
      bar.style.width = pct + '%';
      st.textContent = 'Uploading ' + fmt(e.loaded) + ' / ' +
        fmt(e.total) + '  (' + pct + '%)';
    });
    xhr.addEventListener('load', () => {
      try {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300) {
          bar.style.width = '100%';
          st.textContent = 'Forwarding to Cloudinary…';
          setTimeout(() => {
            st.textContent = 'Done.';
            const cp = 'navigator.clipboard.writeText(\\'' + data.url +
            '\\');return false;';
          result.innerHTML = '<div class="ok">' +
              '<b>Uploaded.</b><br>' +
              'CDN URL: <a href="' + data.url + '" target="_blank">' +
              data.url + '</a>' +
              '<a class="copy" href="#" onclick="' + cp + '">copy</a>' +
              '<pre>' + JSON.stringify(data, null, 2) + '</pre>' +
            '</div>';
            go.disabled = true;
            go.textContent = 'Uploaded';
          }, 250);
        } else {
          const msg = data.error || ('HTTP ' + xhr.status);
          st.innerHTML = '<span class="err">Failed: ' + msg + '</span>';
          go.disabled = false;
        }
      } catch (e) {
        st.innerHTML = '<span class="err">Failed: HTTP ' + xhr.status + '</span>';
        go.disabled = false;
      }
    });
    xhr.addEventListener('error', () => {
      st.innerHTML = '<span class="err">Network error.</span>';
      go.disabled = false;
    });
    go.disabled = true;
    go.textContent = 'Uploading…';
    xhr.send(fd);
  });
</script>
</body>
</html>
"""


def _human_time_remaining(seconds: int) -> str:
    seconds = max(0, seconds)
    mins, secs = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)
    parts = []
    if hrs:
        parts.append(f"{hrs}h")
    if mins:
        parts.append(f"{mins}m")
    if not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


async def upload_page(request: Request) -> HTMLResponse:
    token = request.path_params["token"]
    payload = verify_token(token)
    if not payload or payload.get("type") != "ul":
        return HTMLResponse(
            "<h1>Upload link expired or invalid</h1>"
            "<p>Ask Claude to generate a new upload link.</p>",
            status_code=410,
        )
    target_folder = payload.get("folder") or "(root)"
    target_pid = payload.get("public_id") or "<auto>"
    target = f"{target_folder}/{target_pid}".lstrip("/")
    remaining = int(payload["exp"]) - int(time.time())
    html = _HTML_PAGE.replace("__TARGET__", target).replace(
        "__EXPIRES__", _human_time_remaining(remaining)
    )
    return HTMLResponse(html)


async def upload_handler(request: Request) -> JSONResponse:
    token = request.path_params["token"]
    payload = verify_token(token)
    if not payload or payload.get("type") != "ul":
        return JSONResponse({"error": "upload link expired or invalid"}, status_code=410)

    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        return JSONResponse({"error": "missing form field 'file'"}, status_code=400)

    # Stream the upload to a temp file so we can use chunked Cloudinary upload.
    tmp_dir = tempfile.mkdtemp(prefix="gdrive-mcp-upload-")
    safe_name = os.path.basename(
        getattr(upload, "filename", None) or payload.get("filename") or "video.mp4"
    )
    tmp_path = os.path.join(tmp_dir, safe_name)
    try:
        with open(tmp_path, "wb") as out:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        result = upload_file_stream(
            tmp_path,
            public_id=payload.get("public_id") or None,
            folder=payload.get("folder") or None,
            tags=payload.get("tags") or None,
            overwrite=True,
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"upload failed: {exc}"}, status_code=500)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return JSONResponse(result)


async def upload_status(request: Request) -> JSONResponse:
    """Look up whether the asset has been uploaded yet (by querying Cloudinary)."""
    token = request.path_params["token"]
    payload = verify_token(token)
    if not payload or payload.get("type") != "ul":
        return JSONResponse({"error": "upload link expired or invalid"}, status_code=410)
    public_id = payload.get("public_id") or ""
    folder = payload.get("folder") or ""
    full_pid = f"{folder.rstrip('/')}/{public_id}" if folder else public_id
    try:
        from gdrive_video_mcp.cloudinary_client import get_video

        info = get_video(full_pid)
        return JSONResponse({"ready": True, "public_id": full_pid, **info})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ready": False, "public_id": full_pid, "reason": str(exc)[:200]})


def attach_routes(app: Starlette) -> None:
    app.router.routes.extend(
        [
            Route("/upload/{token}", upload_page, methods=["GET"]),
            Route("/upload/{token}", upload_handler, methods=["POST"]),
            Route("/upload/{token}/status", upload_status, methods=["GET"]),
        ]
    )

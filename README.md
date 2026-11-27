# NoLogo Downloader V6.1 — Stable

NoLogo Downloader is a small FastAPI web app for downloading public TikTok and Douyin video/photo posts.

## Supported and user-tested flows

The V6.1 release retains the V6.0 stable codebase and its tested flows:

- **TikTok video** — downloads video with H.264/audio preference and validates the final audio stream.
- **TikTok Photo Mode** — downloads the photo set as a ZIP.
- **Douyin video** — downloads the public video stream. Whether a watermark is present depends on the URL Douyin exposes for that post.
- **Douyin single image and multi-image albums** — downloads the image(s) as a ZIP; the owner confirmed the tested image files were not watermarked.

## V6.1 convenience controls

- **Dán nhanh** reads text from the system clipboard into the link field when the browser grants Clipboard API permission.
- If clipboard access is unavailable or denied, the page explains how to paste with Ctrl+V (Windows/Linux) or Command+V (macOS).
- **Xóa nhanh** clears the input, previous analysis result, thumbnail, and current link state, then returns focus to the input field.

Clipboard access depends on browser security/permissions and is normally available only in a secure context (HTTPS or localhost). The app does not request clipboard access until the user presses the Dán nhanh button.

## Important limits

- **Douyin posts mixing images and video / Live Photo:** best effort only. The public page may expose the still image but not a separate downloadable motion-video URL. In that case the app downloads the available images; it does not invent a clip or convert a still image into a video.
- When a mixed post does expose usable image/video URLs, the ZIP includes the assets that download successfully. The UI displays the number of images and clips found and warns when no clip URL was exposed.
- The downloader does not crop, blur, paint over, or otherwise erase watermarks. A clean file is possible only when the public source provides a clean media URL.
- Automated tests use fixture JSON and check front-end control wiring. They do not guarantee that every live Douyin post returns all media fields.

## Deployment on Render

Use the repository's `main` branch.

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`
- **Runtime:** Python
- Render's native Python runtime provides FFmpeg/ffprobe for the TikTok H.264/audio validation path.

After deployment, open `/api/health`. A successful V6.1 deployment returns:

```json
{"ok": true, "service": "NoLogo Downloader", "version": "6.1"}
```

## Project files

- `app.py` — FastAPI backend and platform parsing/download logic.
- `static/index.html` — Vietnamese interface and clipboard convenience controls.
- `requirements.txt` — Python dependencies.
- `Procfile` and `render.yaml` — Render startup/deployment configuration.
- `tests/` — fixture-based regression tests.

## Privacy and access

The app does not ask for or store the user's TikTok/Douyin account password or browser login cookies. It uses publicly accessible share URLs and an anonymous visitor session where required by the platform. A post that requires login, is private, or is blocked by platform verification may not be downloadable.

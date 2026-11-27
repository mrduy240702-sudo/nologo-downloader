# NoLogo Downloader V6.0 — Stable

NoLogo Downloader is a small FastAPI web app for downloading public TikTok and Douyin video/photo posts.

## Supported and user-tested flows

The following flows were confirmed by the project owner during manual testing of the stable V5.5 codebase, which is the foundation of this V6.0 release:

- **TikTok video** — downloads video with H.264/audio preference and validates the final audio stream.
- **TikTok Photo Mode** — downloads the photo set as a ZIP.
- **Douyin video** — downloads the public video stream. Whether a watermark is present depends on the URL Douyin exposes for that post.
- **Douyin single image and multi-image albums** — downloads the image(s) as a ZIP; the owner confirmed the tested image files were not watermarked.

## Important limits

- **Douyin posts mixing images and video / Live Photo:** best effort only. The public page may expose the still image but not a separate downloadable motion-video URL. In that case V6.0 downloads the available images; it does not invent a clip or convert a still image into a video.
- When a mixed post does expose usable image/video URLs, the ZIP includes the assets that download successfully. The UI displays the number of images and clips found and warns when no clip URL was exposed.
- The downloader does not crop, blur, paint over, or otherwise erase watermarks. A clean file is possible only when the public source provides a clean media URL.
- Automated tests use fixture JSON and validate parser behavior. They do not guarantee that every live Douyin post returns all media fields.

## Deployment on Render

Use the repository's `main` branch after the V6.0 release PR is merged.

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`
- **Runtime:** Python
- Render's native Python runtime provides FFmpeg/ffprobe for the TikTok H.264/audio validation path.

After deployment, open `/api/health`. A successful V6.0 deployment returns:

```json
{"ok": true, "service": "NoLogo Downloader", "version": "6.0"}
```

## Project files

- `app.py` — FastAPI backend and platform parsing/download logic.
- `static/index.html` — single-page Vietnamese interface.
- `requirements.txt` — Python dependencies.
- `Procfile` and `render.yaml` — Render startup/deployment configuration.
- `tests/test_douyin_slides.py` — fixture-based regression tests for Douyin photo/slide parsing.

## Privacy and access

The app does not ask for or store the user's TikTok/Douyin account password or browser login cookies. It uses publicly accessible share URLs and an anonymous visitor session where required by the platform. A post that requires login, is private, or is blocked by platform verification may not be downloadable.

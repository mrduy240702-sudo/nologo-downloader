# NoLogo Downloader V6.2 — Stable

NoLogo Downloader is a small FastAPI web app for downloading public TikTok and Douyin video/photo posts.

## Supported and user-tested flows

V6.2 retains the existing stable flows:

- **TikTok video** — selects the best video-only source stream and best audio stream available, then muxes them without re-encoding. The default no longer forces H.264/AVC, which could lead to a lower-resolution source being selected when a higher-quality HEVC/AV1 stream is available.
- **TikTok Photo Mode** — downloads the photo set as a ZIP.
- **Douyin video** — downloads the public video stream. Whether a watermark is present depends on the URL Douyin exposes for that post.
- **Douyin single image and multi-image albums** — downloads the image(s) as a ZIP; the owner confirmed the tested image files were not watermarked.

## Video quality selection

- **Cao nhất (giữ chất lượng gốc)** asks yt-dlp for the best source video stream plus the best audio stream. FFmpeg muxes the streams; this path does not intentionally re-encode or lower the video quality.
- Optional maximum-height choices include 4K (2160p), 2K (1440p), 1080p, 720p and 480p. A cap does not upscale a source: the file cannot exceed the resolution actually provided by TikTok.
- The downloader no longer restricts selection to H.264/AVC. Higher resolution HEVC/AV1 source streams may therefore be selected. Some older devices or players may not support every codec/container combination; the file's video quality is preserved rather than transcoded down to H.264.
- The info response reports the maximum video height exposed by the source when yt-dlp provides that metadata.

## V6.2 mobile input behavior

- Text controls use a 16px font to avoid the automatic focus zoom Safari on iPhone/iPad applies to smaller form controls.
- Quick paste and clear controls remain available.

## Important limits

- **Douyin posts mixing images and video / Live Photo:** best effort only. The public page may expose the still image but not a separate downloadable motion-video URL. In that case the app downloads the available images; it does not invent a clip or convert a still image into a video.
- When a mixed post does expose usable image/video URLs, the ZIP includes the assets that download successfully.
- The downloader does not crop, blur, paint over, or otherwise erase watermarks. A clean file is possible only when the public source provides a clean media URL.
- Quality is limited by the formats and resolution exposed by TikTok/Douyin for each post. Choosing 2K/4K cannot create detail absent from the source.

## Deployment on Render

Use the repository's `main` branch.

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`
- **Runtime:** Python
- Render's native Python runtime provides FFmpeg/ffprobe for merging and validating downloaded streams.

After deployment, open `/api/health`. A successful V6.2 deployment returns:

```json
{"ok": true, "service": "NoLogo Downloader", "version": "6.2"}
```

## Project files

- `app.py` — FastAPI backend and platform parsing/download logic.
- `static/index.html` — Vietnamese interface, clipboard controls and quality selection.
- `requirements.txt` — Python dependencies.
- `Procfile` and `render.yaml` — Render startup/deployment configuration.
- `tests/` — regression tests for release health, video format selection and UI behavior.

## Privacy and access

The app does not ask for or store the user's TikTok/Douyin account password or browser login cookies. It uses publicly accessible share URLs and an anonymous visitor session where required by the platform. A post that requires login, is private, or is blocked by platform verification may not be downloadable.

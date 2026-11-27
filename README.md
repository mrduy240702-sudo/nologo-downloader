# NoLogo Downloader V5

- TikTok video: prefers H.264 video with a separate audio stream when available, merges with FFmpeg, and checks the final file with ffprobe. This targets a documented yt-dlp/TikTok case where some HEVC/bytevc1 formats are incorrectly reported as having audio but download without an audio stream.
- Douyin: recognizes `/share/note/<id>/` and `/note/<id>/` share links, searches public embedded page data for image slides, and packages downloadable images as ZIP.
- Douyin video: uses public play_addr variants only. It does not crop, blur, or otherwise erase watermarks. If the public source only exposes a watermarked stream, the watermark remains.
- Keeps V4 TikTok Photo Mode support.

## Deploy
Replace `app.py`, `requirements.txt`, `README.md`, and `static/index.html` in GitHub. Keep `Procfile`. Commit to `main`; deploy latest commit in Render. The build command in this render.yaml installs FFmpeg for audio merging and validation.

## Testing status
Python syntax checked locally. The supplied TikTok link resolves to video ID `7700681905875733780`. The supplied Douyin short link resolves to `/share/note/7707603431581603657/`, confirming it is an image post. Live media extraction from Render still needs to be tested.

# NoLogo Downloader V3

V3 adds a dedicated public-page Douyin extractor and improves share-text handling.

## Changes
- Accepts either a bare URL or full copied share text (including Chinese Douyin share text).
- Resolves `v.douyin.com` short links and extracts the video ID from the redirect.
- Requests the public `iesdouyin.com/share/video/<id>/?from_ssr=1` page using a mobile browser user-agent.
- Parses JSON from `window._ROUTER_DATA` and reads the public `video.play_addr.url_list` URL as supplied.
- Downloads the public playback URL without modifying its path or trying to remove watermarks.
- Keeps TikTok video through yt-dlp and TikTok Photo Mode ZIP through gallery-dl.

## Douyin limits
This is an experimental public-page parser. Douyin can change the page structure, block hosting-provider IPs, region-limit content, or omit public playback data. It does not log in, import account cookies, bypass private access, DRM, or platform security. The source page may provide a watermarked stream; the app does not alter it to strip the watermark.

## Deploy
Replace these files in the existing GitHub repository:
- `app.py`
- `requirements.txt`
- `README.md`
- `static/index.html`

Keep `Procfile` and `render.yaml`. Commit to `main`; Render should auto-deploy.

## Notes
Render Free has limited memory and may not be suitable for large media transfers. Temporary files are currently retained in the service's ephemeral filesystem until the instance restarts; production deployment should add cleanup/background task handling and request-size/time limits.

# NoLogo Downloader V4

- TikTok: follows short-link redirects before checking whether the final URL is `/photo/` or `/video/`. This fixes the V3 routing bug shown when a `vt.tiktok.com` short link redirected to a Photo Mode URL.
- TikTok Photo Mode: uses gallery-dl to retrieve image URLs and downloads the album as ZIP.
- Douyin: creates an anonymous visitor `ttwid` session, opens the public mobile share page, parses `_ROUTER_DATA`, and downloads the playback URL exactly as provided by Douyin.
- No account login or personal browser cookies are requested.
- Does not rewrite playback URLs to strip watermarks. The watermark status depends on the stream Douyin itself provides.

## Deploy
Replace `app.py`, `requirements.txt`, `README.md`, and `static/index.html` in the existing GitHub repository. Keep `Procfile` and `render.yaml`, then commit to `main`.

## Limitations
Douyin may change the share-page structure, block Render IPs, or withhold playback data. This code has syntax-checked locally but has not been tested against the user's exact live links from Render. Render Free resource limits may also affect larger downloads.

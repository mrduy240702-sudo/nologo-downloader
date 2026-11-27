# NoLogo Downloader V5

- TikTok video: prefers H.264 video with a separate audio stream when available, merges with FFmpeg, and checks the final file with ffprobe. This targets a documented yt-dlp/TikTok case where some HEVC/bytevc1 formats are incorrectly reported as having audio but download without an audio stream.
- Douyin: recognizes `/share/note/<id>/` and `/note/<id>/` share links, searches public embedded page data for image slides, and packages downloadable images as ZIP.
- Douyin video: uses public play_addr variants only. It does not crop, blur, or otherwise erase watermarks. If the public source only exposes a watermarked stream, the watermark remains.
- Keeps V4 TikTok Photo Mode support.

## Deploy
Replace `app.py`, `requirements.txt`, `README.md`, and `static/index.html` in GitHub. Keep `Procfile`. Commit to `main`; deploy latest commit in Render. Render's native Python runtime already includes FFmpeg and ffprobe. Use `pip install -r requirements.txt` as the Build Command.

## Testing status
Python syntax checked locally. The supplied TikTok link resolves to video ID `7700681905875733780`. The supplied Douyin short link resolves to `/share/note/7707603431581603657/`, confirming it is an image post. Live media extraction from Render still needs to be tested.




## V5.8 experimental Douyin mixed media
- Request the dedicated `slidesinfo` payload with a generated A-Bogus signature instead of sending a random placeholder signature.
- Select the exact `aweme_id` from `aweme_details`; no fallback to a different post.
- Extract Live Photo MP4 streams from each gallery image's nested `video.play_addr` and compatible address fields.
- Preserve a separate root-level video in a mixed image+video post when it has a positive duration and a video URL.
- Do not treat a root-level MP3 soundtrack (`video.duration == 0`) as a video clip.
- Keeps the V5.5 image URL preference and ZIP containing only successfully downloaded media.
- A-Bogus signing code adapted from F2 under Apache-2.0; see `THIRD_PARTY_NOTICES.md` and `licenses/F2-APACHE-2.0.txt`.

This branch is experimental; GitHub fixture tests do not replace live verification of Douyin share URLs.

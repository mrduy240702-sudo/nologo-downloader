import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
import yt_dlp

app = FastAPI(title="NoLogo Downloader")

ALLOWED_HOSTS = {
    "tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com",
    "vt.tiktok.com", "douyin.com", "www.douyin.com", "v.douyin.com",
    "iesdouyin.com", "www.iesdouyin.com"
}

class LinkRequest(BaseModel):
    url: HttpUrl
    quality: str = "best"

def validate_url(raw: str):
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not any(
        host == domain or host.endswith("." + domain) for domain in ALLOWED_HOSTS
    ):
        raise HTTPException(400, "Chỉ hỗ trợ liên kết TikTok và Douyin hợp lệ.")
    return raw

def ydl_options():
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extract_flat": False,
        "skip_download": True,
        "socket_timeout": 20,
        "retries": 2,
    }

@app.get("/api/health")
def health():
    return {"ok": True, "service": "NoLogo Downloader"}

@app.post("/api/info")
def get_info(body: LinkRequest):
    url = validate_url(str(body.url))
    try:
        with yt_dlp.YoutubeDL(ydl_options()) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            raise ValueError("Không lấy được thông tin bài đăng")
        formats = info.get("formats") or []
        candidates = []
        for f in formats:
            if f.get("vcodec") not in (None, "none"):
                candidates.append({
                    "format_id": f.get("format_id"),
                    "height": f.get("height"),
                    "width": f.get("width"),
                    "ext": f.get("ext"),
                    "filesize": f.get("filesize") or f.get("filesize_approx"),
                    "format_note": f.get("format_note"),
                })
        return {
            "title": info.get("title") or "Nội dung từ mạng xã hội",
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "platform": "Douyin" if "douyin" in url.lower() else "TikTok",
            "formats": candidates,
            "note": "Chất lượng và watermark phụ thuộc các định dạng mà nền tảng cung cấp."
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(422, f"Không thể đọc liên kết này: {str(e)[:240]}")

@app.post("/api/download")
def download(body: LinkRequest):
    url = validate_url(str(body.url))
    quality = body.quality if body.quality in {"best", "1080", "720", "480"} else "best"
    if quality == "best":
        fmt = "bestvideo*+bestaudio/best"
    else:
        h = int(quality)
        fmt = f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
    temp_dir = tempfile.mkdtemp(prefix="nologo_")
    outtmpl = str(Path(temp_dir) / "%(title).80s_%(id)s.%(ext)s")
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": fmt,
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "retries": 2,
        "socket_timeout": 30,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = Path(ydl.prepare_filename(info))
            if not filepath.exists():
                # yt-dlp may merge into mp4
                mp4_path = filepath.with_suffix(".mp4")
                if mp4_path.exists():
                    filepath = mp4_path
            if not filepath.exists():
                matches = list(Path(temp_dir).glob("*"))
                if not matches:
                    raise FileNotFoundError("Không tìm thấy tệp sau khi tải")
                filepath = matches[0]
        safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', filepath.name)[:120]
        return FileResponse(
            filepath,
            media_type="video/mp4" if filepath.suffix.lower() == ".mp4" else "application/octet-stream",
            filename=safe_name,
            background=None
        )
    except Exception as e:
        raise HTTPException(422, f"Tải thất bại: {str(e)[:240]}")

app.mount("/", StaticFiles(directory="static", html=True), name="static")

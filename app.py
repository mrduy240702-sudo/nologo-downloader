import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import requests
import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="NoLogo Downloader", version="4")

ALLOWED_HOSTS = {
    "tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com",
    "vt.tiktok.com", "douyin.com", "www.douyin.com", "v.douyin.com",
    "iesdouyin.com", "www.iesdouyin.com"
}
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

class LinkRequest(BaseModel):
    url: str
    quality: str = "best"

def extract_url(text: str) -> str:
    match = re.search(r"https?://[^\s，。]+", text.strip())
    if not match:
        raise HTTPException(400, "Không tìm thấy đường dẫn http/https trong nội dung bạn dán.")
    return match.group(0).rstrip(".,;，。!！?？)）]】")

def validate_url(raw: str) -> str:
    url = extract_url(raw)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not any(
        host == domain or host.endswith("." + domain) for domain in ALLOWED_HOSTS
    ):
        raise HTTPException(400, "Chỉ hỗ trợ liên kết TikTok và Douyin hợp lệ.")
    return url

def platform_for(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return "Douyin" if ("douyin.com" in host or "iesdouyin.com" in host) else "TikTok"

def resolve_public_url(url: str, platform: str) -> str:
    """Follow public share redirects before classifying the post type."""
    headers = {"User-Agent": MOBILE_UA if platform == "Douyin" else DESKTOP_UA}
    try:
        response = requests.get(url, headers=headers, allow_redirects=True,
                                timeout=(10, 25), stream=True)
        final_url = response.url
        response.close()
    except requests.RequestException as exc:
        raise RuntimeError(f"Không mở được link chia sẻ: {exc}") from exc

    parsed = urlparse(final_url)
    host = (parsed.hostname or "").lower()
    allowed = ALLOWED_HOSTS if platform == "Douyin" else {
        "tiktok.com", "www.tiktok.com", "m.tiktok.com"
    }
    if not any(host == d or host.endswith("." + d) for d in allowed):
        raise RuntimeError("Link chuyển hướng tới tên miền không được hỗ trợ.")
    return final_url

def is_tiktok_photo(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return ("tiktok.com" in host) and "/photo/" in parsed.path.lower()

def gallery_dl(*args, timeout=120):
    executable = shutil.which("gallery-dl")
    if not executable:
        raise RuntimeError("Máy chủ chưa cài gallery-dl. Kiểm tra requirements.txt.")
    result = subprocess.run([executable, *args], capture_output=True,
                            text=True, timeout=timeout, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "gallery-dl không lấy được dữ liệu").strip()
        raise RuntimeError(detail[-900:])
    return result.stdout.strip()

def tiktok_photo_urls(url: str):
    output = gallery_dl(
        "-g",
        "-o", "extractor.tiktok.audio=false",
        "-o", "extractor.tiktok.videos=false",
        url, timeout=90
    )
    urls = [x.strip() for x in output.splitlines()
            if x.strip().startswith(("http://", "https://"))]
    if not urls:
        raise RuntimeError("Không tìm thấy ảnh trong bài đăng. Có thể bài bị giới hạn hoặc TikTok đổi cấu trúc.")
    return urls

def create_douyin_session():
    """Create an anonymous visitor ttwid; this is not a user's account cookie."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": MOBILE_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    try:
        response = session.post(
            "https://ttwid.bytedance.com/ttwid/union/register/",
            json={
                "region": "cn",
                "aid": 1768,
                "needFid": False,
                "service": "www.ixigua.com",
                "migrate_info": {"ticket": "", "source": "node"},
                "cbUrlProtocol": "https",
                "union": True,
            },
            headers={"User-Agent": MOBILE_UA, "Content-Type": "application/json"},
            timeout=(10, 20),
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Không tạo được phiên khách Douyin: {exc}") from exc
    return session

def extract_douyin_id(url: str, session: requests.Session) -> str:
    response = session.get(url, allow_redirects=True,
                           headers={"Referer": "https://www.douyin.com/"},
                           timeout=(10, 25))
    response.raise_for_status()
    final_url = response.url
    for pattern in (
        r"/video/(\d+)", r"/share/video/(\d+)",
        r"[?&]modal_id=(\d+)", r"[?&]item_id=(\d+)",
    ):
        match = re.search(pattern, final_url)
        if match:
            return match.group(1)
    for pattern in (r'"aweme_id"\s*:\s*"(\d+)"',
                    r'"itemId"\s*:\s*"(\d+)"',
                    r'"modal_id"\s*:\s*"(\d+)"'):
        match = re.search(pattern, response.text)
        if match:
            return match.group(1)
    raise RuntimeError("Đã mở link Douyin nhưng không tìm thấy mã video.")

def parse_router_data(html: str):
    marker = "_ROUTER_DATA"
    pos = html.find(marker)
    if pos < 0:
        raise RuntimeError("Trang chia sẻ Douyin không trả về dữ liệu _ROUTER_DATA.")
    eq = html.find("=", pos + len(marker))
    if eq < 0:
        raise RuntimeError("Không tìm thấy dấu '=' sau _ROUTER_DATA.")
    decoder = json.JSONDecoder()
    for i in range(eq + 1, min(len(html), eq + 25000)):
        if html[i] in "{[":
            try:
                data, _ = decoder.raw_decode(html[i:])
                return data
            except json.JSONDecodeError:
                continue
    raise RuntimeError("Dữ liệu _ROUTER_DATA không phải JSON hợp lệ.")

def walk_objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_objects(child)

def extract_douyin_public_data(url: str):
    session = create_douyin_session()
    aweme_id = extract_douyin_id(url, session)
    share_url = f"https://www.iesdouyin.com/share/video/{aweme_id}/"
    response = session.get(
        share_url,
        headers={"Referer": "https://www.douyin.com/"},
        timeout=(10, 30),
    )
    response.raise_for_status()
    router = parse_router_data(response.text)

    for obj in walk_objects(router):
        video = obj.get("video")
        if not isinstance(video, dict):
            continue
        play_addr = video.get("play_addr") or {}
        urls = play_addr.get("url_list") or []
        if not urls:
            continue
        desc = obj.get("desc") or obj.get("description") or f"Douyin_{aweme_id}"
        cover = video.get("cover") or video.get("origin_cover") or {}
        cover_urls = cover.get("url_list") or []
        # Keep the public playback URL exactly as supplied by Douyin.
        return {
            "aweme_id": aweme_id,
            "title": str(desc)[:300],
            "thumbnail": cover_urls[0] if cover_urls else None,
            "play_url": urls[0],
            "session": session,
        }
    raise RuntimeError(
        "Đã mở được trang chia sẻ nhưng không thấy play_addr trong dữ liệu công khai. "
        "Douyin có thể đã đổi cấu trúc, chặn IP máy chủ hoặc giới hạn bài đăng."
    )

def ydl_options():
    return {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "extract_flat": False, "skip_download": True,
        "socket_timeout": 30, "retries": 2,
        "http_headers": {"User-Agent": DESKTOP_UA},
    }

@app.get("/api/health")
def health():
    return {"ok": True, "service": "NoLogo Downloader", "version": "4"}

@app.post("/api/info")
def get_info(body: LinkRequest):
    original_url = validate_url(body.url)
    platform = platform_for(original_url)

    if platform == "Douyin":
        try:
            data = extract_douyin_public_data(original_url)
            return {
                "title": data["title"], "thumbnail": data["thumbnail"],
                "platform": "Douyin", "media_type": "video", "formats": [],
                "note": "Đọc từ trang chia sẻ công khai. Giữ nguyên luồng phát mà Douyin cung cấp.",
            }
        except Exception as exc:
            raise HTTPException(422, f"Không phân tích được Douyin: {str(exc)[:650]}")

    try:
        resolved = resolve_public_url(original_url, "TikTok")
    except Exception as exc:
        raise HTTPException(422, f"Không mở được link TikTok: {str(exc)[:500]}")

    # Important: classify the resolved URL, not the original short URL.
    if is_tiktok_photo(resolved):
        try:
            images = tiktok_photo_urls(resolved)
            return {
                "title": "TikTok Photo Mode", "thumbnail": images[0],
                "platform": "TikTok", "media_type": "photos",
                "image_count": len(images), "formats": [],
                "note": "Album ảnh sẽ được tải thành file ZIP.",
            }
        except Exception as exc:
            raise HTTPException(422, f"Không đọc được album ảnh TikTok: {str(exc)[:500]}")

    try:
        with yt_dlp.YoutubeDL(ydl_options()) as ydl:
            info = ydl.extract_info(resolved, download=False)
        if not info:
            raise ValueError("Nguồn không trả về thông tin bài đăng.")
        formats = [{
            "format_id": f.get("format_id"), "height": f.get("height"),
            "width": f.get("width"), "ext": f.get("ext")
        } for f in (info.get("formats") or [])
          if f.get("vcodec") not in (None, "none")]
        return {
            "title": info.get("title") or "TikTok video",
            "thumbnail": info.get("thumbnail"), "platform": "TikTok",
            "media_type": "video", "formats": formats,
            "note": "Chất lượng phụ thuộc định dạng nguồn cung cấp.",
        }
    except Exception as exc:
        raise HTTPException(422, f"Không thể phân tích TikTok: {str(exc)[:650]}")

@app.post("/api/download")
def download(body: LinkRequest):
    original_url = validate_url(body.url)
    platform = platform_for(original_url)

    if platform == "Douyin":
        try:
            data = extract_douyin_public_data(original_url)
            temp_dir = Path(tempfile.mkdtemp(prefix="nologo_douyin_"))
            file_path = temp_dir / f"douyin_{data['aweme_id']}.mp4"
            with data["session"].get(
                data["play_url"], stream=True,
                headers={"Referer": "https://www.iesdouyin.com/"},
                timeout=(15, 90),
            ) as response:
                response.raise_for_status()
                if "text/html" in response.headers.get("Content-Type", "").lower():
                    raise RuntimeError("Douyin trả về HTML thay vì tệp video.")
                with file_path.open("wb") as out:
                    for chunk in response.iter_content(256 * 1024):
                        if chunk:
                            out.write(chunk)
            if file_path.stat().st_size < 1024:
                raise RuntimeError("Tệp video tải về không hợp lệ.")
            return FileResponse(file_path, media_type="video/mp4",
                                filename=file_path.name)
        except Exception as exc:
            raise HTTPException(422, f"Tải Douyin thất bại: {str(exc)[:650]}")

    try:
        resolved = resolve_public_url(original_url, "TikTok")
    except Exception as exc:
        raise HTTPException(422, f"Không mở được link TikTok: {str(exc)[:500]}")

    if is_tiktok_photo(resolved):
        temp_dir = Path(tempfile.mkdtemp(prefix="nologo_photos_"))
        try:
            gallery_dl(
                "--no-mtime", "-D", str(temp_dir),
                "-o", "extractor.tiktok.audio=false",
                "-o", "extractor.tiktok.videos=false",
                resolved, timeout=180
            )
            files = [p for p in temp_dir.rglob("*") if p.is_file()]
            if not files:
                raise RuntimeError("Không tải được ảnh nào từ album.")
            zip_path = temp_dir / "tiktok-photo-album.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in files:
                    if path != zip_path:
                        archive.write(path, path.relative_to(temp_dir))
            return FileResponse(zip_path, media_type="application/zip",
                                filename=zip_path.name)
        except Exception as exc:
            raise HTTPException(422, f"Tải album ảnh thất bại: {str(exc)[:650]}")

    quality = body.quality if body.quality in {"best", "1080", "720", "480"} else "best"
    fmt = "bestvideo*+bestaudio/best" if quality == "best" else (
        f"bestvideo[height<={int(quality)}]+bestaudio/best[height<={int(quality)}]/best"
    )
    temp_dir = tempfile.mkdtemp(prefix="nologo_tiktok_")
    opts = {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "format": fmt,
        "outtmpl": str(Path(temp_dir) / "%(title).80s_%(id)s.%(ext)s"),
        "merge_output_format": "mp4", "retries": 2, "socket_timeout": 30,
        "http_headers": {"User-Agent": DESKTOP_UA},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(resolved, download=True)
            path = Path(ydl.prepare_filename(info))
            if not path.exists() and path.with_suffix(".mp4").exists():
                path = path.with_suffix(".mp4")
            if not path.exists():
                matches = [p for p in Path(temp_dir).glob("*") if p.is_file()]
                if not matches:
                    raise FileNotFoundError("Không tìm thấy tệp sau khi tải.")
                path = matches[0]
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", path.name)[:120]
        return FileResponse(path, media_type="video/mp4", filename=safe_name)
    except Exception as exc:
        raise HTTPException(422, f"Tải TikTok thất bại: {str(exc)[:650]}")

app.mount("/", StaticFiles(directory="static", html=True), name="static")

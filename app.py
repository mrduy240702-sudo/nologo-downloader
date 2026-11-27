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

app = FastAPI(title="NoLogo Downloader", version="3.0")

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
    # Accept either a bare URL or the full share text copied from TikTok/Douyin.
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
    return "Douyin" if "douyin.com" in urlparse(url).netloc.lower() or "iesdouyin.com" in url.lower() else "TikTok"

def resolve_douyin_id(url: str) -> str:
    try:
        response = requests.get(
            url, headers={"User-Agent": MOBILE_UA},
            allow_redirects=True, timeout=(10, 25)
        )
        response.raise_for_status()
        final_url = response.url
        candidates = [
            re.search(r"/video/(\d+)", final_url),
            re.search(r"/share/video/(\d+)", final_url),
            re.search(r"[?&]modal_id=(\d+)", final_url),
            re.search(r"[?&]item_id=(\d+)", final_url),
        ]
        for match in candidates:
            if match:
                return match.group(1)
        # Some share redirects land on a page whose HTML contains the item id.
        for pattern in (
            r'"aweme_id"\s*:\s*"(\d+)"',
            r'"itemId"\s*:\s*"(\d+)"',
            r'"modal_id"\s*:\s*"(\d+)"',
        ):
            match = re.search(pattern, response.text)
            if match:
                return match.group(1)
        raise RuntimeError("Đã mở link chia sẻ nhưng không tìm thấy mã video trong trang đích.")
    except requests.RequestException as exc:
        raise RuntimeError(f"Không mở được link Douyin: {exc}") from exc

def parse_router_data(html: str):
    # Parse the JSON object assigned to window._ROUTER_DATA without evaluating page JS.
    markers = ("window._ROUTER_DATA", "_ROUTER_DATA")
    start = -1
    for marker in markers:
        pos = html.find(marker)
        if pos >= 0:
            eq = html.find("=", pos + len(marker))
            if eq >= 0:
                start = eq + 1
                break
    if start < 0:
        raise RuntimeError("Trang chia sẻ Douyin không chứa dữ liệu _ROUTER_DATA công khai.")
    decoder = json.JSONDecoder()
    for index in range(start, min(len(html), start + 20000)):
        if html[index] in "{[":
            try:
                data, _ = decoder.raw_decode(html[index:])
                return data
            except json.JSONDecodeError:
                continue
    raise RuntimeError("Không đọc được JSON _ROUTER_DATA từ trang chia sẻ Douyin.")

def walk_objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_objects(child)

def extract_douyin_public_data(url: str):
    aweme_id = resolve_douyin_id(url)
    share_url = f"https://www.iesdouyin.com/share/video/{aweme_id}/?from_ssr=1"
    response = requests.get(
        share_url,
        headers={
            "User-Agent": MOBILE_UA,
            "Referer": "https://www.douyin.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
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
        desc = obj.get("desc") or obj.get("description") or "Douyin video"
        cover = video.get("cover") or video.get("origin_cover") or {}
        cover_urls = cover.get("url_list") or []
        # Use only the public playback URL returned by the share page as-is.
        # Do not alter endpoint paths or attempt to bypass watermark/security controls.
        return {
            "aweme_id": aweme_id,
            "title": str(desc)[:300],
            "thumbnail": cover_urls[0] if cover_urls else None,
            "play_url": urls[0],
            "source": "Douyin public share page",
        }
    raise RuntimeError(
        "Douyin không cung cấp địa chỉ phát video trên trang chia sẻ công khai này. "
        "Bài có thể bị giới hạn khu vực, riêng tư hoặc trang chia sẻ đã thay đổi."
    )

def is_tiktok_photo(url: str) -> bool:
    parsed = urlparse(url)
    return "tiktok.com" in (parsed.hostname or "").lower() and "/photo/" in parsed.path.lower()

def gallery_dl(*args, timeout=90):
    executable = shutil.which("gallery-dl")
    if not executable:
        raise RuntimeError("Máy chủ chưa cài gallery-dl. Hãy kiểm tra requirements.txt và triển khai lại.")
    result = subprocess.run(
        [executable, *args], capture_output=True, text=True,
        timeout=timeout, check=False
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "gallery-dl không lấy được dữ liệu").strip()
        raise RuntimeError(detail[-900:])
    return result.stdout.strip()

def tiktok_photo_urls(url: str):
    output = gallery_dl(
        "-g",
        "-o", "extractor.tiktok.audio=false",
        "-o", "extractor.tiktok.videos=false",
        url, timeout=60
    )
    urls = [line.strip() for line in output.splitlines() if line.strip().startswith(("http://", "https://"))]
    if not urls:
        raise RuntimeError("Không tìm thấy ảnh trong bài đăng. Bài có thể không phải Photo Mode hoặc nền tảng từ chối yêu cầu.")
    return urls

def ydl_options(skip_download=True):
    return {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "extract_flat": False, "skip_download": skip_download,
        "socket_timeout": 30, "retries": 2,
        "http_headers": {"User-Agent": DESKTOP_UA},
    }

@app.get("/api/health")
def health():
    return {"ok": True, "service": "NoLogo Downloader", "version": "3"}

@app.post("/api/info")
def get_info(body: LinkRequest):
    url = validate_url(body.url)
    platform = platform_for(url)

    if platform == "Douyin":
        try:
            data = extract_douyin_public_data(url)
            return {
                "title": data["title"],
                "thumbnail": data["thumbnail"],
                "platform": "Douyin",
                "media_type": "video",
                "formats": [],
                "note": "Đọc từ trang chia sẻ công khai. Chất lượng phụ thuộc URL phát mà Douyin cung cấp.",
            }
        except Exception as exc:
            raise HTTPException(422, f"Không phân tích được Douyin: {str(exc)[:650]}")

    if is_tiktok_photo(url):
        try:
            images = tiktok_photo_urls(url)
            return {
                "title": "TikTok Photo Mode",
                "thumbnail": images[0],
                "platform": "TikTok",
                "media_type": "photos",
                "image_count": len(images),
                "formats": [],
                "note": "Album ảnh sẽ được tải thành file ZIP.",
            }
        except Exception as exc:
            raise HTTPException(422, f"Không đọc được album ảnh TikTok: {str(exc)[:500]}")

    try:
        with yt_dlp.YoutubeDL(ydl_options()) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            raise ValueError("Nguồn không trả về thông tin bài đăng.")
        formats = []
        for item in info.get("formats") or []:
            if item.get("vcodec") not in (None, "none"):
                formats.append({
                    "format_id": item.get("format_id"),
                    "height": item.get("height"),
                    "width": item.get("width"),
                    "ext": item.get("ext"),
                })
        return {
            "title": info.get("title") or "TikTok video",
            "thumbnail": info.get("thumbnail"),
            "platform": "TikTok",
            "media_type": "video",
            "formats": formats,
            "note": "Chất lượng phụ thuộc định dạng nguồn cung cấp.",
        }
    except Exception as exc:
        raise HTTPException(422, f"Không thể phân tích TikTok: {str(exc)[:650]}")

@app.post("/api/download")
def download(body: LinkRequest):
    url = validate_url(body.url)
    platform = platform_for(url)

    if platform == "Douyin":
        try:
            data = extract_douyin_public_data(url)
            temp_dir = Path(tempfile.mkdtemp(prefix="nologo_douyin_"))
            file_path = temp_dir / f"douyin_{data['aweme_id']}.mp4"
            with requests.get(
                data["play_url"],
                headers={
                    "User-Agent": MOBILE_UA,
                    "Referer": "https://www.iesdouyin.com/",
                },
                stream=True,
                timeout=(15, 90),
            ) as response:
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "")
                if "text/html" in content_type.lower():
                    raise RuntimeError("Douyin trả về trang HTML thay vì tệp video.")
                with file_path.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            output.write(chunk)
            if file_path.stat().st_size < 1024:
                raise RuntimeError("Tệp tải về quá nhỏ, có thể nguồn không trả video hợp lệ.")
            return FileResponse(file_path, media_type="video/mp4", filename=file_path.name)
        except Exception as exc:
            raise HTTPException(422, f"Tải Douyin thất bại: {str(exc)[:650]}")

    if is_tiktok_photo(url):
        temp_dir = Path(tempfile.mkdtemp(prefix="nologo_photos_"))
        try:
            gallery_dl(
                "--no-mtime", "-D", str(temp_dir),
                "-o", "extractor.tiktok.audio=false",
                "-o", "extractor.tiktok.videos=false",
                url, timeout=180
            )
            files = [p for p in temp_dir.rglob("*") if p.is_file()]
            if not files:
                raise RuntimeError("Không tải được ảnh nào từ album.")
            zip_path = temp_dir / "tiktok-photo-album.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in files:
                    if path != zip_path:
                        archive.write(path, path.relative_to(temp_dir))
            return FileResponse(zip_path, media_type="application/zip", filename=zip_path.name)
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
            info = ydl.extract_info(url, download=True)
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

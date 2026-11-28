import json
import mimetypes
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

app = FastAPI(title="NoLogo Downloader", version="6.2")

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
        r"/video/(\d+)", r"/share/video/(\d+)", r"/slides/(\d+)", r"/share/slides/(\d+)", r"/note/(\d+)", r"/share/note/(\d+)",
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


DOUYIN_MEDIA_HOSTS = (
    "douyinpic.com", "byteimg.com", "pstatp.com", "ibytedtos.com",
    "douyinvod.com", "zjcdn.com", "snssdk.com", "bytecdn.cn", "aweme.snssdk.com",
    "bytedance.net", "bytedance.com", "douyinstatic.com", "douyin.com", "iesdouyin.com", "toutiao.com",
)

def is_allowed_douyin_media_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and any(host == d or host.endswith("." + d) for d in DOUYIN_MEDIA_HOSTS)
    except Exception:
        return False

def _url_list(value):
    """Normalize URL fields used by Douyin's different image/video payloads."""
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, dict):
        values = value.get("url_list") or value.get("urls") or []
        for key in ("url", "src"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                values = list(values) + [candidate]
    elif isinstance(value, list):
        values = value
    else:
        values = []
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(
        u.strip() for u in values
        if isinstance(u, str) and u.strip().startswith("https://")
        and is_allowed_douyin_media_url(u.strip())
    ))


def _slide_image_urls(slide: dict) -> list[str]:
    """
    Prefer the last item in url_list (commonly the original/high-resolution
    image). Do not use download_url_list: Douyin may watermark those downloads.
    """
    for key in ("url_list", "origin_image", "display_image", "image"):
        urls = _url_list(slide.get(key))
        if urls:
            return list(reversed(urls))
    return []

def _uri_video_fallback(video: dict) -> list[str]:
    play_addr = video.get("play_addr")
    if not isinstance(play_addr, dict):
        return []
    uri = play_addr.get("uri")
    if not isinstance(uri, str) or not uri.strip():
        return []
    from urllib.parse import quote
    video_id = quote(uri.strip(), safe="")
    return [
        f"https://www.iesdouyin.com/aweme/v1/play/?video_id={video_id}&ratio=1080p&line=0",
        f"https://aweme.snssdk.com/aweme/v1/play/?video_id={video_id}&ratio=1080p&line=0",
        f"https://aweme.snssdk.com/aweme/v1/play/?video_id={video_id}&ratio=720p&line=0",
        f"https://aweme.snssdk.com/aweme/v1/play/?video_id={video_id}&line=0",
    ]

def _clean_play_candidates(urls):
    """Prefer the platform's public play URL when it exposes a playwm variant."""
    result = []
    for url in urls:
        clean = url.replace("/playwm/", "/play/").replace("playwm", "play")
        if clean != url:
            result.append(clean)
        result.append(url)
    return list(dict.fromkeys(result))


def _slide_video_urls(slide: dict) -> list[str]:
    candidates = []
    for key in ("video", "video_play_addr", "video_download_addr"):
        video = slide.get(key)
        if not isinstance(video, dict):
            continue
        for addr_key in ("play_addr", "play_addr_h264", "play_addr_265", "play_addr_bytevc1", "play_addr_lowbr", "download_addr"):
            candidates.extend(_url_list(video.get(addr_key)))
        for gear in video.get("bit_rate") or []:
            if isinstance(gear, dict):
                candidates.extend(_url_list(gear.get("play_addr")))
        if not any(_url_list(video.get(k)) for k in ("play_addr", "play_addr_h264", "play_addr_265", "play_addr_bytevc1", "play_addr_lowbr", "download_addr")):
            candidates.extend(_uri_video_fallback(video))
    return _clean_play_candidates(list(dict.fromkeys(candidates)))

def _find_douyin_slide_list(router, aweme_id: str):
    item = _find_douyin_aweme_item(router, aweme_id)
    if not item:
        return None, []
    images = item.get("images")
    if isinstance(images, list) and images:
        return item, images
    info = item.get("image_post_info")
    if isinstance(info, dict):
        images = info.get("images") or info.get("image_list")
        if isinstance(images, list) and images:
            return item, images
    for key in ("image_list", "image_infos", "original_images"):
        images = item.get(key)
        if isinstance(images, list) and images:
            return item, images
    return item, []


def _find_douyin_aweme_item(payload, aweme_id: str):
    """Only return the requested aweme. Never guess from an unrelated media object."""
    wanted = str(aweme_id)
    for obj in walk_objects(payload):
        obj_id = str(obj.get("aweme_id") or obj.get("item_id") or obj.get("modal_id") or "")
        if obj_id != wanted:
            continue
        has_media = (
            isinstance(obj.get("video"), dict)
            or isinstance(obj.get("images"), list)
            or isinstance(obj.get("image_post_info"), dict)
            or isinstance(obj.get("image_list"), list)
            or isinstance(obj.get("image_infos"), list)
        )
        if has_media:
            return obj
    return None

def _find_douyin_music_url(router):
    for obj in walk_objects(router):
        music = obj.get("music")
        if not isinstance(music, dict):
            continue
        urls = _url_list(music.get("play_url"))
        if urls:
            return urls[0]
    return None


def _douyin_data_from_item(item, aweme_id, session, fallback_music=None):
    title = item.get("desc") or item.get("title") or f"Douyin_{aweme_id}"
    title = str(title).strip()[:300]

    images = item.get("images")
    image_info = item.get("image_post_info")
    if not isinstance(images, list) or not images:
        if isinstance(image_info, dict):
            images = image_info.get("images") or image_info.get("image_list")
    if not isinstance(images, list) or not images:
        for key in ("image_list", "image_infos", "original_images"):
            candidate = item.get(key)
            if isinstance(candidate, list) and candidate:
                images = candidate
                break

    music = item.get("music") if isinstance(item.get("music"), dict) else {}
    music_urls = _url_list(music.get("play_url"))
    music_url = music_urls[0] if music_urls else fallback_music

    if isinstance(images, list) and images:
        items = []
        for index, slide in enumerate(images, 1):
            if not isinstance(slide, dict):
                continue
            image_urls = _slide_image_urls(slide)
            video_urls = _slide_video_urls(slide)
            if image_urls or video_urls:
                video_obj = slide.get("video") if isinstance(slide.get("video"), dict) else {}
                items.append({
                    "index": index,
                    "kind": "live_photo" if image_urls and video_urls else ("video" if video_urls else "image"),
                    "image_urls": image_urls,
                    "video_urls": video_urls,
                    "duration_ms": video_obj.get("duration"),
                })
        if items:
            first_image = next((x["image_urls"][0] for x in items if x["image_urls"]), None)
            return {
                "aweme_id": aweme_id, "title": title, "media_type": "slides",
                "items": items, "thumbnail": first_image, "music_url": music_url,
                "session": session,
            }

    video = item.get("video") if isinstance(item.get("video"), dict) else {}
    video_urls = []
    for key in ("play_addr", "play_addr_h264", "play_addr_265", "play_addr_bytevc1"):
        video_urls.extend(_url_list(video.get(key)))
    for rate in video.get("bit_rate") or []:
        if isinstance(rate, dict):
            video_urls.extend(_url_list(rate.get("play_addr")))
    if not video_urls:
        video_urls.extend(_uri_video_fallback(video))
    video_urls = _clean_play_candidates(list(dict.fromkeys(video_urls)))
    if not video_urls:
        return None

    cover_urls = []
    for key in ("origin_cover", "cover", "dynamic_cover"):
        cover_urls.extend(_url_list(video.get(key)))
    return {
        "aweme_id": aweme_id, "title": title, "media_type": "video",
        "thumbnail": cover_urls[0] if cover_urls else None,
        "play_url": video_urls[0], "video_urls": video_urls,
        "items": [], "music_url": music_url, "session": session,
    }

def extract_douyin_public_data(url: str):
    """
    Multi-strategy public parser:
    1) SSR share pages (slides, note, video)
    2) legacy public iteminfo JSON endpoint
    The SSR page alone may not contain the full slide/live-photo payload.
    """
    session = create_douyin_session()
    aweme_id = extract_douyin_id(url, session)
    resolved = session.get(url, allow_redirects=True, timeout=(10, 25))
    resolved.raise_for_status()
    resolved_url = resolved.url
    is_slides = bool(re.search(r"/(?:share/)?slides/\d+", resolved_url)) or "is_slides=1" in resolved_url
    is_note = bool(re.search(r"/(?:share/)?note/\d+", resolved_url))

    if is_slides:
        paths = ("slides", "note", "video")
    elif is_note:
        paths = ("note", "slides", "video")
    else:
        paths = ("video", "note", "slides")

    errors = []
    music_url = None
    for path in paths:
        suffix = "/?is_slides=1" if path == "slides" else "/"
        share_url = f"https://www.iesdouyin.com/share/{path}/{aweme_id}{suffix}"
        try:
            response = session.get(
                share_url,
                headers={"Referer": "https://www.douyin.com/", "Accept": "text/html,application/xhtml+xml"},
                timeout=(10, 30),
            )
            response.raise_for_status()
            router = parse_router_data(response.text)
            music_url = music_url or _find_douyin_music_url(router)
            item = _find_douyin_aweme_item(router, aweme_id)
            if item:
                data = _douyin_data_from_item(item, aweme_id, session, music_url)
                if data:
                    return data
            errors.append(f"{path}: SSR không chứa media URL dùng được")
        except Exception as exc:
            errors.append(f"{path}: {str(exc)[:130]}")

    # Older public endpoint. It often returns the complete image list even when
    # the slides SSR shell contains only partial metadata.
    for host in ("www.iesdouyin.com", "www.douyin.com"):
        api_url = f"https://{host}/web/api/v2/aweme/iteminfo/?item_ids={aweme_id}"
        try:
            response = session.get(
                api_url,
                headers={
                    "Referer": f"https://www.iesdouyin.com/share/slides/{aweme_id}/",
                    "Accept": "application/json,text/plain,*/*",
                },
                timeout=(10, 25),
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError:
                payload = json.loads(response.text)
            item = _find_douyin_aweme_item(payload, aweme_id)
            if item:
                data = _douyin_data_from_item(item, aweme_id, session, music_url)
                if data:
                    return data
            errors.append(f"{host} iteminfo: phản hồi không có media URL")
        except Exception as exc:
            errors.append(f"{host} iteminfo: {str(exc)[:130]}")

    raise RuntimeError(
        "Không lấy được media từ các nguồn công khai. Chi tiết: " + " | ".join(errors[:5])
    )

def ydl_options():
    return {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "extract_flat": False, "skip_download": True,
        "socket_timeout": 30, "retries": 2,
        "http_headers": {"User-Agent": DESKTOP_UA},
    }


def tiktok_format_selector(quality: str) -> str:
    """
    Select the best source video/audio without forcing H.264.
    H.264-only selection can silently choose a lower resolution when TikTok
    exposes a higher-resolution HEVC/AV1 stream.
    """
    if quality == "best":
        return "bestvideo*+bestaudio/best"
    if quality in {"1080", "720", "480"}:
        height = int(quality)
        return (
            f"bestvideo*[height<={height}]+bestaudio/"
            f"best[height<={height}]"
        )
    return "bestvideo*+bestaudio/best"


def has_audio_stream(path: Path) -> bool:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return False
    result = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=20
    )
    return result.returncode == 0 and "audio" in result.stdout.lower()


def _download_douyin_asset(session, urls, media_kind: str, max_bytes: int):
    failures = []
    for media_url in urls:
        try:
            if not is_allowed_douyin_media_url(media_url):
                raise RuntimeError("CDN host không được hỗ trợ")
            with session.get(
                media_url,
                headers={"Referer": "https://www.douyin.com/"},
                timeout=(10, 90),
                stream=True,
            ) as response:
                response.raise_for_status()
                if not is_allowed_douyin_media_url(response.url):
                    raise RuntimeError("CDN chuyển hướng tới host không được hỗ trợ")
                content = response.content
                if not content or len(content) > max_bytes:
                    raise RuntimeError("Tệp rỗng hoặc vượt giới hạn kích thước")
                ctype = response.headers.get("Content-Type", "").lower()
                if "text/html" in ctype:
                    raise RuntimeError("CDN trả HTML thay vì media")

                if media_kind == "image":
                    if content.startswith(b"\xff\xd8\xff"):
                        ext = ".jpg"
                    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
                        ext = ".png"
                    elif content[:4] == b"RIFF" and content[8:12] == b"WEBP":
                        ext = ".webp"
                    elif content[:6] in (b"GIF87a", b"GIF89a"):
                        ext = ".gif"
                    elif b"ftypavif" in content[:32]:
                        ext = ".avif"
                    else:
                        raise RuntimeError(f"Phản hồi không phải ảnh hợp lệ ({ctype or 'không rõ định dạng'})")
                else:
                    if b"ftyp" not in content[:32] and not content.startswith(b"\x1aE\xdf\xa3"):
                        raise RuntimeError(f"Phản hồi không phải video hợp lệ ({ctype or 'không rõ định dạng'})")
                    ext = ".mp4"
                return content, ext
        except Exception as exc:
            failures.append(str(exc)[:110])
    raise RuntimeError("; ".join(failures[:3]) or "Không có URL media hợp lệ")

@app.get("/api/health")
def health():
    return {"ok": True, "service": "NoLogo Downloader", "version": "6.2"}

@app.post("/api/info")
def get_info(body: LinkRequest):
    original_url = validate_url(body.url)
    platform = platform_for(original_url)

    if platform == "Douyin":
        try:
            data = extract_douyin_public_data(original_url)
            image_count = sum(1 for item in data.get("items", []) if item.get("image_urls"))
            video_count = sum(1 for item in data.get("items", []) if item.get("video_urls"))
            if data["media_type"] == "slides" and image_count and not video_count:
                note = (
                    "Đã tìm thấy ảnh. Dữ liệu công khai của bài này chưa cung cấp "
                    "đường dẫn clip Live Photo/video có thể tải; ZIP có thể chỉ gồm ảnh tĩnh."
                )
            elif data["media_type"] == "slides":
                note = (
                    "Đã tìm thấy các tệp ảnh/video có đường dẫn công khai. "
                    "ZIP chỉ chứa những tệp tải thành công."
                )
            else:
                note = "Video Douyin sẵn sàng tải; chất lượng và watermark phụ thuộc nguồn công khai."
            return {
                "title": data["title"], "thumbnail": data["thumbnail"],
                "platform": "Douyin", "media_type": data["media_type"],
                "image_count": image_count, "video_count": video_count,
                "slide_count": len(data.get("items", [])), "formats": [],
                "note": note,
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
            "width": f.get("width"), "ext": f.get("ext"),
            "vcodec": f.get("vcodec"), "tbr": f.get("tbr"),
        } for f in (info.get("formats") or [])
          if f.get("vcodec") not in (None, "none")]
        max_height = max((int(f.get("height") or 0) for f in formats), default=0)
        return {
            "title": info.get("title") or "TikTok video",
            "thumbnail": info.get("thumbnail"), "platform": "TikTok",
            "media_type": "video", "formats": formats,
            "max_height": max_height or None,
            "note": (
                f"Nguồn đang cung cấp tối đa {max_height}p. "
                "Chế độ cao nhất sẽ tải độ phân giải tốt nhất mà TikTok cho phép."
                if max_height else "Chất lượng phụ thuộc định dạng nguồn cung cấp."
            ),
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
            if data["media_type"] in ("photos", "slides"):
                zip_path = temp_dir / f"douyin_media_{data['aweme_id']}.zip"
                saved, failed = 0, []
                items = data.get("items") or [
                    {"index": i, "kind": "image", "image_urls": [u], "video_urls": []}
                    for i, u in enumerate(data.get("image_urls", []), 1)
                ]
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                    for item in items:
                        idx = item["index"]
                        for kind, urls, max_bytes in (
                            ("image", item.get("image_urls") or [], 40 * 1024 * 1024),
                            ("motion", item.get("video_urls") or [], 180 * 1024 * 1024),
                        ):
                            if not urls:
                                continue
                            try:
                                content, ext = _download_douyin_asset(
                                    data["session"], urls, "image" if kind == "image" else "video", max_bytes
                                )
                                archive.writestr(f"{idx:03d}-{kind}{ext}", content)
                                saved += 1
                            except Exception as exc:
                                failed.append(f"slide {idx} {kind}: {str(exc)[:160]}")
                if saved == 0:
                    raise RuntimeError(
                        "Douyin có trả dữ liệu bài đăng nhưng không tải được media nào: "
                        + "; ".join(failed[:4])
                    )
                return FileResponse(
                    zip_path,
                    media_type="application/zip",
                    filename=zip_path.name,
                    headers={
                        "X-NoLogo-Partial-Download": str(len(failed)),
                        "X-NoLogo-Saved-Assets": str(saved),
                    },
                )
            file_path = temp_dir / f"douyin_{data['aweme_id']}.mp4"
            with data["session"].get(data["play_url"], stream=True, headers={"Referer": "https://www.douyin.com/"}, timeout=(15, 90)) as response:
                response.raise_for_status()
                if "text/html" in response.headers.get("Content-Type", "").lower():
                    raise RuntimeError("Douyin trả về HTML thay vì video.")
                with file_path.open("wb") as out:
                    for chunk in response.iter_content(256 * 1024):
                        if chunk:
                            out.write(chunk)
            if file_path.stat().st_size < 1024:
                raise RuntimeError("Tệp video Douyin không hợp lệ.")
            return FileResponse(file_path, media_type="video/mp4", filename=file_path.name)
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
    fmt = tiktok_format_selector(quality)
    temp_dir = tempfile.mkdtemp(prefix="nologo_tiktok_")
    opts = {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "format": fmt,
        "outtmpl": str(Path(temp_dir) / "%(title).80s_%(id)s.%(ext)s"),
        "merge_output_format": "mp4/mkv", "retries": 3, "socket_timeout": 45,
        "http_headers": {"User-Agent": DESKTOP_UA},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(resolved, download=True)
            path = Path(ydl.prepare_filename(info))
            if not path.exists():
                candidates = [
                    path.with_suffix(ext)
                    for ext in (".mp4", ".mkv", ".mov", ".webm")
                    if path.with_suffix(ext).exists()
                ]
                if not candidates:
                    candidates = [
                        p for p in Path(temp_dir).glob("*")
                        if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm"}
                    ]
                if not candidates:
                    raise FileNotFoundError("Không tìm thấy tệp video sau khi ghép luồng.")
                path = max(candidates, key=lambda p: p.stat().st_size)
            if not has_audio_stream(path):
                raise RuntimeError(
                    "Tệp video tải về không có luồng âm thanh hợp lệ. "
                    "Máy chủ không tự hạ độ phân giải để đổi lấy một bản kém chất lượng hơn."
                )
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", path.name)[:120]
        return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream", filename=safe_name)
    except Exception as exc:
        raise HTTPException(422, f"Tải TikTok thất bại: {str(exc)[:650]}")

app.mount("/", StaticFiles(directory="static", html=True), name="static")

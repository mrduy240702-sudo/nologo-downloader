import json
import unittest
from app import (
    _find_douyin_music_url, _find_douyin_slide_list,
    _slide_image_urls, _slide_video_urls, _douyin_data_from_item, _clean_play_candidates, extract_douyin_id, parse_router_data, is_allowed_douyin_media_url,
)

AWEME_ID = "7708178105391047397"

class FakeResponse:
    def __init__(self, url, text=""):
        self.url = url
        self.text = text
    def raise_for_status(self):
        return None

class FakeSession:
    def get(self, *args, **kwargs):
        return FakeResponse(f"https://www.iesdouyin.com/share/slides/{AWEME_ID}/?is_slides=1")

class DouyinSlidesTests(unittest.TestCase):
    def setUp(self):
        self.router = {
            "aweme_detail": {
                "aweme_id": AWEME_ID,
                "desc": "Test mixed slides",
                "is_slides": True,
                "images": [
                    {
                        "url_list": ["https://p3-pc-sign.douyinpic.com/slide-1.jpg"],
                        "download_url_list": ["https://p3-pc-sign.douyinpic.com/slide-1-original.jpg"],
                        "live_photo_type": 1,
                        "video": {
                            "duration": 5038,
                            "play_addr": {"url_list": ["https://v5-dy-o.zjcdn.com/clip-1.mp4"]},
                        },
                    },
                    {
                        "url_list": ["https://p3-pc-sign.douyinpic.com/slide-2.jpg"],
                        "video": None,
                    },
                    {
                        "video": {
                            "duration": 3200,
                            "play_addr_h264": {"url_list": ["https://v5-dy-o.zjcdn.com/clip-3.mp4"]},
                        },
                    },
                ],
                "music": {
                    "play_url": {"url_list": ["https://sf1-cdn-tos.douyinstatic.com/music.mp3"]}
                },
            }
        }

    def test_share_slides_id_is_extracted(self):
        self.assertEqual(extract_douyin_id("https://v.douyin.com/example/", FakeSession()), AWEME_ID)

    def test_parser_reads_router_assignment(self):
        raw = {"aweme_detail": {"aweme_id": AWEME_ID}}
        parsed = parse_router_data("window._ROUTER_DATA = " + json.dumps(raw) + ";")
        self.assertEqual(parsed["aweme_detail"]["aweme_id"], AWEME_ID)

    def test_mixed_slides_are_found_in_order(self):
        obj, slides = _find_douyin_slide_list(self.router, AWEME_ID)
        self.assertIsNotNone(obj)
        self.assertEqual(len(slides), 3)
        self.assertEqual(len(_slide_image_urls(slides[0])), 1)
        self.assertEqual(_slide_image_urls(slides[0])[0], "https://p3-pc-sign.douyinpic.com/slide-1.jpg")
        self.assertEqual(len(_slide_video_urls(slides[0])), 1)
        self.assertEqual(len(_slide_image_urls(slides[1])), 1)
        self.assertEqual(len(_slide_video_urls(slides[1])), 0)
        self.assertEqual(len(_slide_video_urls(slides[2])), 1)

    def test_watermarked_download_url_is_not_selected_as_image(self):
        slide = {
            "download_url_list": ["https://p3-pc-sign.douyinpic.com/watermarked.jpg"],
            "url_list": [
                "https://p3-pc-sign.douyinpic.com/preview.jpg",
                "https://p3-pc-sign.douyinpic.com/original-clean.jpg",
            ],
        }
        urls = _slide_image_urls(slide)
        self.assertEqual(urls[0], "https://p3-pc-sign.douyinpic.com/original-clean.jpg")
        self.assertNotIn("https://p3-pc-sign.douyinpic.com/watermarked.jpg", urls)

    def test_unrelated_aweme_is_not_used_as_fallback(self):
        payload = {"items": [{"aweme_id": "1111111111111111111", "images": [{"url_list": ["https://p3-pc-sign.douyinpic.com/random.jpg"]}]}]}
        self.assertIsNone(_find_douyin_slide_list(payload, AWEME_ID)[0])

    def test_live_photo_uri_has_public_play_endpoint_fallback(self):
        slide = {"video": {"play_addr": {"uri": "live-photo-uri"}}}
        urls = _slide_video_urls(slide)
        self.assertTrue(urls)
        self.assertIn("/aweme/v1/play/?video_id=live-photo-uri", urls[0])
        self.assertIn("watermark=0", urls[0])
        self.assertTrue(is_allowed_douyin_media_url(urls[0]))

    def test_live_photo_direct_video_play_addr_is_extracted(self):
        slide = {
            "url_list": ["https://p3-pc-sign.douyinpic.com/live-photo.jpg"],
            "video_play_addr": {
                "url_list": ["https://v5-dy-o.zjcdn.com/live-photo-motion.mp4"]
            },
        }
        urls = _slide_video_urls(slide)
        self.assertEqual(urls, ["https://v5-dy-o.zjcdn.com/live-photo-motion.mp4"])

    def test_live_photo_video_download_addr_uri_is_extracted(self):
        slide = {
            "video_download_addr": {
                "uri": "live-motion-123",
            }
        }
        urls = _slide_video_urls(slide)
        self.assertTrue(urls)
        self.assertIn("live-motion-123", urls[0])
        self.assertTrue(is_allowed_douyin_media_url(urls[0]))

    def test_live_photo_video_url_can_be_a_direct_string(self):
        slide = {
            "video_play_addr": "https://v5-dy-o.zjcdn.com/live-motion-direct.mp4"
        }
        urls = _slide_video_urls(slide)
        self.assertEqual(urls, ["https://v5-dy-o.zjcdn.com/live-motion-direct.mp4"])

    def test_background_music_is_separate_from_live_photo_clips(self):
        self.assertEqual(_find_douyin_music_url(self.router), "https://sf1-cdn-tos.douyinstatic.com/music.mp3")

    def test_iteminfo_fallback_can_extract_mixed_media(self):
        item = self.router["aweme_detail"]
        data = _douyin_data_from_item(item, AWEME_ID, object())
        self.assertEqual(data["media_type"], "slides")
        self.assertEqual(len(data["items"]), 3)
        self.assertEqual(data["music_url"], "https://sf1-cdn-tos.douyinstatic.com/music.mp3")

    def test_playwm_candidates_prefer_public_play_variant(self):
        original = "https://aweme.snssdk.com/aweme/v1/playwm/?video_id=abc"
        candidates = _clean_play_candidates([original])
        self.assertEqual(candidates[0], "https://aweme.snssdk.com/aweme/v1/play/?video_id=abc")
        self.assertIn(original, candidates)

if __name__ == "__main__":
    unittest.main()
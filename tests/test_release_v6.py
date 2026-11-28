import unittest

from app import health, tiktok_format_selector


class StableReleaseTests(unittest.TestCase):
    def test_health_reports_v6_2(self):
        payload = health()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["service"], "NoLogo Downloader")
        self.assertEqual(payload["version"], "6.2")

    def test_default_video_download_does_not_force_h264(self):
        selector = tiktok_format_selector("best")
        self.assertEqual(selector, "bestvideo*+bestaudio/best")
        self.assertNotIn("avc1", selector)
        self.assertNotIn("vcodec", selector)

    def test_resolution_caps_include_2k_and_4k(self):
        self.assertIn("height<=2160", tiktok_format_selector("2160"))
        self.assertIn("height<=1440", tiktok_format_selector("1440"))
        self.assertIn("height<=1080", tiktok_format_selector("1080"))


if __name__ == "__main__":
    unittest.main()

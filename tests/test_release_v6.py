import unittest

from app import health


class StableReleaseTests(unittest.TestCase):
    def test_health_reports_v6(self):
        payload = health()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["service"], "NoLogo Downloader")
        self.assertEqual(payload["version"], "6.0")


if __name__ == "__main__":
    unittest.main()

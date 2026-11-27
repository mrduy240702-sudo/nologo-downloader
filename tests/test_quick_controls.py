import unittest
from pathlib import Path


class QuickControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")

    def test_quick_paste_button_and_clipboard_api_are_present(self):
        self.assertIn('id="quickPaste"', self.html)
        self.assertIn('navigator.clipboard.readText()', self.html)
        self.assertIn("Ctrl+V", self.html)

    def test_quick_clear_resets_previous_analysis(self):
        self.assertIn('id="quickClear"', self.html)
        self.assertIn('$("url").value=""', self.html)
        self.assertIn('currentText=""', self.html)
        self.assertIn('currentInfo=null', self.html)
        self.assertIn('$("result").style.display="none"', self.html)
        self.assertIn('$("url").focus()', self.html)


if __name__ == "__main__":
    unittest.main()

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

    def test_text_controls_use_16px_font_to_prevent_ios_auto_zoom(self):
        self.assertIn('font:16px/1.5', self.html)
        self.assertIn('textarea,input,select{font-size:16px}', self.html)

    def test_quality_options_include_2k_and_4k(self):
        self.assertIn('value="2160"', self.html)
        self.assertIn('value="1440"', self.html)

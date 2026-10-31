import io
import unittest

from PIL import Image

from app.core.visual import analyze_palette


def png(color):
    out = io.BytesIO()
    Image.new("RGB", (120, 80), color).save(out, format="PNG")
    return out.getvalue()


class VisualPaletteTests(unittest.TestCase):
    def test_approved_palette_color_is_not_flagged(self):
        result = analyze_palette(png("#18324f"), ["#18324f", "#ffffff"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["findings"], [])

    def test_material_unapproved_color_has_measured_nearest_match(self):
        result = analyze_palette(png("#f00018"), ["#18324f", "#ffffff"])
        self.assertEqual(len(result["findings"]), 1)
        self.assertGreater(result["findings"][0]["delta_e"], 18)
        self.assertEqual(result["findings"][0]["nearest_approved"], "#FFFFFF")

    def test_missing_palette_is_explicitly_unavailable(self):
        self.assertEqual(analyze_palette(png("white"), []) ["status"], "unavailable")

    def test_corrupt_image_rejected(self):
        with self.assertRaises(ValueError):
            analyze_palette(b"not an image", ["#ffffff"])


if __name__ == "__main__":
    unittest.main()

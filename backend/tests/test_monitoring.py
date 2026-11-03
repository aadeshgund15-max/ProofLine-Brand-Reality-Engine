import unittest

from app.services.monitoring import (_changed_image_visuals, _image_asset_manifest,
                                    _image_assets_changed, _meaningful_change,
                                    _next_text, _removed_image_urls, _stored_image_manifest)


class MonitoringChangeTests(unittest.TestCase):
    def test_whitespace_only_change_is_not_material(self):
        self.assertFalse(_meaningful_change("Acme offers reliable home energy monitoring.",
                                            "Acme offers reliable\n home energy monitoring."))

    def test_numeric_claim_change_is_material(self):
        self.assertTrue(_meaningful_change("Our device reduces electricity use by 60% for every home.",
                                           "Our device reduces electricity use by 50% for every home."))

    def test_tiny_nonclaim_edit_is_suppressed(self):
        self.assertFalse(_meaningful_change("Explore our product and learn more today.",
                                            "Explore our product and learn more now."))

    def test_normalized_text_is_bounded_and_compacted(self):
        self.assertEqual(_next_text(type("Result", (), {"text": " one\n two ".strip()})()), "one two")

    def test_image_manifest_hashes_bounded_public_url_references(self):
        calls = []

        def fetcher(url, **kwargs):
            calls.append((url, kwargs))
            return type("Fetch", (), {"content_type": "image/png", "body": b"image-v1", "truncated": False})()

        manifest = _image_asset_manifest(
            b'<html><img src="/assets/logo.png?signature=private"><img src="data:image/png,x"></html>',
            "https://example.org/page", fetcher)
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["observed"], 1)
        self.assertEqual(calls[0][0], "https://example.org/assets/logo.png?signature=private")
        self.assertLessEqual(calls[0][1]["max_bytes"], 1_000_000)
        self.assertEqual(manifest["visual_assets"][0]["image_bytes"], b"image-v1")
        self.assertNotIn("private", str(_stored_image_manifest(manifest)))
        self.assertEqual(manifest["visual_assets"][0]["url_label"], "https://example.org/assets/logo.png")
        self.assertNotIn("visual_assets", _stored_image_manifest(manifest))

    def test_image_change_requires_two_complete_manifests(self):
        old = {"status": "complete", "hashes": {"opaque-key": "old"}}
        current = {"status": "complete", "hashes": {"opaque-key": "new"}}
        incomplete = {"status": "partial", "hashes": {}}
        self.assertTrue(_image_assets_changed(old, current))
        self.assertFalse(_image_assets_changed(old, incomplete))
        self.assertFalse(_image_assets_changed(None, current))

    def test_only_changed_images_are_sent_for_visual_review(self):
        old = {"status": "complete", "hashes": {"opaque-key": "old"}}
        current = {"status": "complete", "hashes": {"opaque-key": "new"},
                   "visual_assets": [{"url_key": "opaque-key", "url_label": "https://example.org/a.png",
                                      "label": "Logo", "image_bytes": b"new-bytes"}]}
        changed = _changed_image_visuals(old, current)
        self.assertEqual(len(changed), 1)
        self.assertIn("Logo", changed[0]["label"])
        self.assertIn("https://example.org/a.png", changed[0]["label"])

    def test_removed_images_are_reported_but_not_visualized_as_current_assets(self):
        old = {"status": "complete", "hashes": {"opaque-key": "old"},
               "url_labels": {"opaque-key": "https://example.org/old.png"}}
        current = {"status": "complete", "hashes": {}, "visual_assets": []}
        self.assertEqual(_changed_image_visuals(old, current), [])
        self.assertEqual(_removed_image_urls(old, current), ["https://example.org/old.png"])


if __name__ == "__main__":
    unittest.main()

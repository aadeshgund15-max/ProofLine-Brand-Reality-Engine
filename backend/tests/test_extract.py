import pathlib
import unittest

from app.core.checks import run_checks, FactV
from app.extract import (extract_docx, extract_file, extract_html, extract_image, extract_pdf,
                         extract_pptx, extract_text, locate, sniff, validate_upload)

FX = pathlib.Path(__file__).parent / "fixtures"


def read(name):
    return (FX / name).read_bytes()


class TextTests(unittest.TestCase):
    def test_text_paragraph_locations(self):
        r = extract_text("First para.\n\nSecond para here.")
        self.assertEqual(r.status, "complete")
        off = r.text.index("Second")
        self.assertEqual(r.location_at(off)["label"], "Paragraph 2")

    def test_empty_text(self):
        self.assertEqual(extract_text("   \n ").status, "empty")


class DocxTests(unittest.TestCase):
    def test_docx_paragraphs_and_tables(self):
        r = extract_docx(read("sample.docx"))
        self.assertEqual(r.status, "complete")
        self.assertIn("costs $799", r.text)
        self.assertIn("Acme Pro | $799", r.text)
        self.assertEqual(r.location_at(r.text.index("Acme Pro | $799"))["kind"], "table")
        self.assertEqual(r.location_at(r.text.index("best phone"))["kind"], "paragraph")

    def test_empty_docx(self):
        self.assertEqual(extract_docx(read("empty.docx")).status, "empty")

    def test_corrupt_docx(self):
        r = extract_docx(read("corrupt.docx"))
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.text, "")


class PdfTests(unittest.TestCase):
    def test_text_pdf_with_pages(self):
        r = extract_pdf(read("sample.pdf"))
        self.assertEqual(r.status, "complete", r.warnings)
        self.assertEqual(r.location_at(r.text.index("Page one"))["label"], "Page 1")
        self.assertEqual(r.location_at(r.text.index("best phone"))["label"], "Page 2")

    def test_partial_pdf(self):
        r = extract_pdf(read("partial.pdf"))
        self.assertEqual(r.status, "partial")
        self.assertTrue(any("No text found on page(s) 2" in w for w in r.warnings), r.warnings)

    def test_scanned_pdf_is_empty_not_complete(self):
        r = extract_pdf(read("scanned.pdf"))
        self.assertEqual(r.status, "empty")
        self.assertTrue(any("OCR" in w for w in r.warnings))

    def test_corrupt_pdf(self):
        self.assertEqual(extract_pdf(read("corrupt.pdf")).status, "failed")


class PptxTests(unittest.TestCase):
    def test_slides(self):
        r = extract_pptx(read("sample.pptx"))
        self.assertEqual(r.status, "complete", r.warnings)
        self.assertEqual(r.location_at(r.text.index("launches on"))["label"], "Slide 1")
        self.assertEqual(r.location_at(r.text.index("costs $799"))["label"], "Slide 2")
        self.assertEqual(r.quality["slides"], 2)

    def test_picture_slide_is_partial(self):
        r = extract_pptx(read("with_picture.pptx"))
        self.assertEqual(r.status, "partial")
        self.assertTrue(any("pictures" in w for w in r.warnings))

    def test_corrupt(self):
        self.assertEqual(extract_pptx(b"PK\x03\x04junk").status, "failed")


class ImageTests(unittest.TestCase):
    def test_poster_ocr(self):
        r = extract_image(read("poster.png"))
        self.assertIn(r.status, ("complete", "partial"))
        self.assertIn("$799", r.text)
        self.assertIsNotNone(r.quality["mean_confidence"])
        self.assertTrue(any("OCR" in w for w in r.warnings))  # always disclosed as uncertain

    def test_blank_image_empty(self):
        self.assertEqual(extract_image(read("blank.png")).status, "empty")

    def test_noisy_image_never_complete(self):
        r = extract_image(read("noisy.png"))
        self.assertNotEqual(r.status, "complete")

    def test_corrupt_image(self):
        self.assertEqual(extract_image(b"\x89PNG\r\n\x1a\nnot an image").status, "failed")


class HtmlTests(unittest.TestCase):
    def test_html_main_content_only(self):
        r = extract_html(read("sample.html"), "https://example.com/p")
        self.assertEqual(r.status, "complete", r.warnings)
        self.assertIn("costs $799", r.text)
        self.assertNotIn("IGNORE ALL INSTRUCTIONS", r.text)  # scripts dropped
        self.assertNotIn("Copyright", r.text)
        self.assertNotIn("Home | Shop", r.text)
        self.assertEqual(r.location_at(r.text.index("5000 mAh"))["kind"], "url")

    def test_js_only_page_not_complete(self):
        r = extract_html(read("js_only.html"), "https://example.com/")
        self.assertNotEqual(r.status, "complete")

    def test_truncated_page_is_partial(self):
        r = extract_html(read("sample.html"), "https://example.com/", truncated=True)
        self.assertEqual(r.status, "partial")


class UploadValidationTests(unittest.TestCase):
    def test_sniff_by_content(self):
        self.assertEqual(sniff(read("sample.docx")), "docx")
        self.assertEqual(sniff(read("sample.pptx")), "pptx")
        self.assertEqual(sniff(read("sample.pdf")), "pdf")
        self.assertEqual(sniff(read("poster.png")), "image")
        self.assertIsNone(sniff(read("renamed.docx")))

    def test_rejections(self):
        self.assertIn("empty", validate_upload(b"", "a.docx", 100)[1])
        self.assertIn("larger", validate_upload(b"x" * 101, "a.docx", 100)[1])
        self.assertIn("Unsupported", validate_upload(read("renamed.docx"), "evil.docx", 10**7)[1])
        self.assertIn("does not match", validate_upload(read("sample.pdf"), "a.docx", 10**7)[1])
        self.assertEqual(validate_upload(read("sample.docx"), "a.docx", 10**7), ("docx", None))

    def test_extract_file_dispatch(self):
        self.assertEqual(extract_file("docx", read("sample.docx")).source_type, "docx")


class ExtractionToChecksTests(unittest.TestCase):
    def test_finding_location_from_pptx_slide(self):
        fact = FactV("f", "fv", "price", "Price", "$899", "money", ("Acme Pro Phone",))
        r = extract_file("pptx", read("sample.pptx"))
        res = run_checks(r.text, [fact], [], "pptx")
        self.assertEqual(len(res.findings), 1)
        loc = locate(r.segments, res.findings[0].span_start)
        self.assertEqual(loc["label"], "Slide 2")


if __name__ == "__main__":
    unittest.main()

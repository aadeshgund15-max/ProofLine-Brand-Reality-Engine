import io
import unittest

from PIL import Image

from app.core.visual import (analyze_logo_references, analyze_palette, extract_visual_assets,
                             analyze_document_typography_layout, render_pdf_visual_pages)
from app.providers.base import NoLlm, NoSearch
from app.services.review import compute_review


def png(color):
    out = io.BytesIO()
    Image.new("RGB", (120, 80), color).save(out, format="PNG")
    return out.getvalue()


def logo_png(size=(120, 60), rotate=0):
    from PIL import ImageDraw
    image = Image.new("RGBA", size, "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, size[0] // 3, size[1] - 8), fill="#123456")
    draw.polygon([(size[0] // 2, 8), (size[0] - 8, size[1] // 2),
                  (size[0] // 2, size[1] - 8)], fill="#F0A030")
    out = io.BytesIO()
    image.rotate(rotate, expand=True).save(out, format="PNG")
    return out.getvalue()


class VisualPaletteTests(unittest.TestCase):
    def test_logo_reference_similarity_is_a_human_review_candidate(self):
        from PIL import Image
        reference_bytes = logo_png()
        resized = Image.open(io.BytesIO(reference_bytes)).resize((240, 120))
        candidate_bytes = io.BytesIO()
        resized.save(candidate_bytes, format="PNG")
        reference = {"id": "asset-1", "name": "Primary", "image_bytes": reference_bytes}
        candidate = {"image_bytes": candidate_bytes.getvalue(), "kind": "pptx_image", "label": "Picture 1",
                     "page_number": 2, "coordinates": {"x_inches": 1.0}, "rotation_degrees": 0,
                     "display_aspect_ratio": 2.0}
        result = analyze_logo_references([candidate], [reference])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["matches"][0]["status"], "similar_to_approved_logo")
        self.assertEqual(result["matches"][0]["review_status"], "needs_human_review")
        self.assertEqual(result["matches"][0]["page_number"], 2)
        self.assertEqual(result["matches"][0]["reference_asset_id"], "asset-1")

    def test_logo_rotation_and_aspect_ratio_issues_are_flagged(self):
        reference = {"id": "asset-1", "name": "Primary", "image_bytes": logo_png()}
        candidate = {"image_bytes": logo_png(), "kind": "pptx_image", "label": "Brand logo",
                     "page_number": 1, "coordinates": None, "rotation_degrees": 90,
                     "display_aspect_ratio": 3.5}
        result = analyze_logo_references([candidate], [reference])
        self.assertEqual(result["matches"][0]["status"], "similar_to_approved_logo")
        self.assertEqual(set(result["matches"][0]["issues"]), {"aspect_ratio_mismatch", "rotated_placement"})

    def test_rotated_raster_logo_is_matched_and_flagged(self):
        reference = {"id": "asset-1", "name": "Primary", "image_bytes": logo_png()}
        candidate = {"image_bytes": logo_png(rotate=90), "kind": "pdf_image", "label": "Embedded PDF image",
                     "page_number": 2, "coordinates": {"x_points": 40}, "rotation_degrees": 0}
        result = analyze_logo_references([candidate], [reference])
        self.assertEqual(result["matches"][0]["status"], "similar_to_approved_logo")
        self.assertIn("rotated_raster_content", result["matches"][0]["issues"])

    def test_missing_logo_references_are_unavailable(self):
        result = analyze_logo_references([{"image_bytes": logo_png()}], [])
        self.assertEqual(result["status"], "unavailable")

    def test_pptx_embedded_image_keeps_slide_and_geometry(self):
        from pptx import Presentation
        from pptx.util import Inches
        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        picture = slide.shapes.add_picture(io.BytesIO(logo_png()), Inches(1), Inches(2), width=Inches(2))
        picture.rotation = 90
        data = io.BytesIO()
        presentation.save(data)
        assets = extract_visual_assets(data.getvalue(), "pptx")
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["page_number"], 1)
        self.assertAlmostEqual(assets[0]["rotation_degrees"], 90)
        self.assertAlmostEqual(assets[0]["coordinates"]["x_inches"], 1)

    def test_pdf_embedded_image_keeps_page_and_coordinates(self):
        import pymupdf
        document = pymupdf.open()
        page = document.new_page(width=300, height=300)
        page.insert_image(pymupdf.Rect(20, 30, 140, 90), stream=logo_png())
        source = document.tobytes()
        document.close()
        assets = extract_visual_assets(source, "pdf")
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["page_number"], 1)
        self.assertAlmostEqual(assets[0]["coordinates"]["x_points"], 20)

    def test_review_findings_keep_logo_page_and_coordinates(self):
        candidate = {"image_bytes": logo_png(), "kind": "pptx_image", "label": "Logo",
                     "page_number": 3, "coordinates": {"x_inches": 1.25, "y_inches": 0.5},
                     "rotation_degrees": 0, "display_aspect_ratio": 2.0}
        reference = {"id": "asset-1", "name": "Primary", "image_bytes": logo_png()}
        computed = compute_review({"extracted_text": "Ordinary product description.", "source_type": "pptx",
                                   "extraction_status": "complete", "extraction_warnings": []},
                                  [], [], NoSearch(), NoLlm(), visual_assets=[candidate], approved_logos=[reference])
        finding = next(item for item in computed.findings if item.category == "logo_reference_match")
        self.assertEqual(finding.location["label"], "Slide 3")
        self.assertEqual(finding.location["kind"], "slide")
        self.assertEqual(finding.location["x_inches"], 1.25)

    def test_pptx_typography_and_layout_rules_return_slide_locations(self):
        from pptx import Presentation
        from pptx.util import Inches, Pt
        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        shape = slide.shapes.add_textbox(Inches(0.1), Inches(0.3), Inches(3), Inches(1))
        run = shape.text_frame.paragraphs[0].add_run()
        run.text = "A short headline"
        run.font.name = "Arial"
        run.font.size = Pt(12)
        data = io.BytesIO()
        presentation.save(data)
        result = analyze_document_typography_layout(data.getvalue(), "pptx", approved_fonts=["Brand Sans"],
                                                    min_font_size_pt=18, min_margin_inches=0.5)
        self.assertEqual(result["typography"]["status"], "partial")
        self.assertEqual(result["typography"]["findings"][0]["page_number"], 1)
        self.assertIn("Arial", result["typography"]["findings"][0]["message"])
        self.assertEqual(result["layout"]["findings"][0]["kind"], "slide")

    def test_pdf_typography_uses_extracted_font_metadata(self):
        import pymupdf
        document = pymupdf.open()
        page = document.new_page(width=300, height=300)
        page.insert_text((20, 30), "Label", fontname="tiro", fontsize=10)
        data = document.tobytes()
        document.close()
        result = analyze_document_typography_layout(data, "pdf", approved_fonts=["Helvetica"], min_font_size_pt=12)
        self.assertEqual(result["typography"]["status"], "partial")
        self.assertTrue(result["typography"]["fonts_detected"])
        self.assertEqual(result["typography"]["findings"][0]["page_number"], 1)

    def test_approved_palette_color_is_not_flagged(self):
        result = analyze_palette(png("#18324f"), ["#18324f", "#ffffff"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["findings"], [])

    def test_material_unapproved_color_has_measured_nearest_match(self):
        result = analyze_palette(png("#f00018"), ["#18324f", "#ffffff"])
        self.assertEqual(len(result["findings"]), 1)
        self.assertGreater(result["findings"][0]["delta_e"], 18)
        self.assertEqual(result["findings"][0]["nearest_approved"], "#FFFFFF")
        self.assertEqual(result["findings"][0]["coordinates"]["x_percent"], 0)
        self.assertEqual(result["findings"][0]["coordinates"]["width_percent"], 100)

    def test_palette_tolerances_are_configurable_and_bounded(self):
        self.assertEqual(analyze_palette(png("#f00018"), ["#18324f"], delta_threshold=200)["findings"], [])
        with self.assertRaises(ValueError):
            analyze_palette(png("#f00018"), ["#18324f"], delta_threshold=201)

    def test_missing_palette_is_explicitly_unavailable(self):
        self.assertEqual(analyze_palette(png("white"), []) ["status"], "unavailable")

    def test_corrupt_image_rejected(self):
        with self.assertRaises(ValueError):
            analyze_palette(b"not an image", ["#ffffff"])

    def test_pdf_visual_pages_are_rendered_with_page_numbers(self):
        import pymupdf
        document = pymupdf.open()
        for color in ((0.9, 0.0, 0.0), (0.0, 0.8, 0.0) , (0.0, 0.0, 0.9)):
            page = document.new_page(width=200, height=200)
            page.draw_rect(pymupdf.Rect(0, 0, 200, 200), color=None, fill=color)
        source = document.tobytes()
        document.close()

        pages, page_count = render_pdf_visual_pages(source, max_pages=2)

        self.assertEqual(page_count, 3)
        self.assertEqual([page["page_number"] for page in pages], [1, 2])
        self.assertTrue(all(page["image_bytes"].startswith(b"\x89PNG") for page in pages))

    def test_rendered_pdf_page_can_be_screened_against_palette(self):
        import pymupdf
        document = pymupdf.open()
        page = document.new_page(width=120, height=80)
        page.draw_rect(pymupdf.Rect(0, 0, 120, 80), color=None, fill=(0.95, 0.0, 0.05))
        source = document.tobytes()
        document.close()

        pages, total = render_pdf_visual_pages(source)
        result = analyze_palette(pages[0]["image_bytes"], ["#18324F", "#FFFFFF"])

        self.assertEqual(total, 1)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["findings"])


if __name__ == "__main__":
    unittest.main()

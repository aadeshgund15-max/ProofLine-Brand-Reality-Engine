"""Conservative image palette analysis using CIE Lab (Delta E 1976)."""
from __future__ import annotations

import io
import base64
import math
import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class PaletteFinding:
    color: str
    nearest_approved: str
    delta_e: float
    coverage: float


def _normalize_font_family(value: str) -> str:
    family = re.sub(r"^[A-Z]{6}\+", "", value.strip())
    family = re.sub(r"(?i)(?:[-_ ]?(?:regular|bold|italic|oblique|medium|light|semibold|black|mt))+$", "", family)
    return family.strip().casefold()


def render_pdf_visual_pages(pdf_bytes: bytes, *, max_pages: int = 10, max_dimension: int = 1400) -> tuple[list[dict], int]:
    """Render a bounded set of PDF pages for visual screening; never execute document content."""
    try:
        import pymupdf
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError("PDF could not be opened for visual page rendering") from exc
    try:
        total_pages = len(document)
        rendered: list[dict] = []
        for index in range(min(total_pages, max(1, min(max_pages, 20)))):
            page = document.load_page(index)
            width, height = float(page.rect.width), float(page.rect.height)
            if width <= 0 or height <= 0:
                continue
            scale = min(1.25, max_dimension / max(width, height))
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            rendered.append({"page_number": index + 1, "image_bytes": pixmap.tobytes("png")})
        return rendered, total_pages
    except Exception as exc:
        raise ValueError("PDF page rendering failed") from exc
    finally:
        document.close()


def extract_visual_assets(document_bytes: bytes, source_type: str, *, max_assets: int = 80) -> list[dict]:
    """Extract raster visual objects with source locations from supported inputs.

    PDF vector graphics and page-composite logos are not treated as separately
    identified assets. PPTX image objects and embedded PDF raster objects retain
    their source slide/page and geometry.
    """
    source_type = source_type.lower()
    if source_type == "image":
        return [{"image_bytes": document_bytes, "kind": "image", "label": "Uploaded image",
                 "page_number": None, "coordinates": None, "rotation_degrees": 0.0,
                 "display_aspect_ratio": None}]
    assets: list[dict] = []
    if source_type == "pptx":
        try:
            from pptx import Presentation
            from pptx.enum.shapes import MSO_SHAPE_TYPE
            presentation = Presentation(io.BytesIO(document_bytes))
        except Exception as exc:
            raise ValueError("Presentation could not be opened for embedded image analysis") from exc
        for slide_no, slide in enumerate(presentation.slides, 1):
            for shape in slide.shapes:
                if shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
                    continue
                try:
                    image = shape.image
                    width, height = int(shape.width), int(shape.height)
                    nv = getattr(shape._element, "nvPicPr", None)
                    props = getattr(nv, "cNvPr", None)
                    title = (getattr(props, "title", None) or "").strip()
                    descr = (getattr(props, "descr", None) or "").strip()
                    assets.append({"image_bytes": image.blob, "kind": "pptx_image",
                                   "label": " ".join(x for x in (title, descr, shape.name) if x),
                                   "page_number": slide_no,
                                   "coordinates": {"x_inches": round(shape.left / 914400, 3),
                                                   "y_inches": round(shape.top / 914400, 3),
                                                   "width_inches": round(width / 914400, 3),
                                                   "height_inches": round(height / 914400, 3)},
                                   "rotation_degrees": float(shape.rotation or 0),
                                   "display_aspect_ratio": width / height if height else None})
                except Exception:
                    continue
                if len(assets) >= max_assets:
                    return assets
        return assets
    if source_type == "pdf":
        try:
            import pymupdf
            document = pymupdf.open(stream=document_bytes, filetype="pdf")
        except Exception as exc:
            raise ValueError("PDF could not be opened for embedded image analysis") from exc
        try:
            for page_no, page in enumerate(document, 1):
                for image in page.get_images(full=True):
                    xref = image[0]
                    try:
                        extracted = document.extract_image(xref)
                        rects = page.get_image_rects(xref)
                    except Exception:
                        continue
                    for rect in rects:
                        width, height = float(rect.width), float(rect.height)
                        assets.append({"image_bytes": extracted["image"], "kind": "pdf_image",
                                       "label": "Embedded PDF image", "page_number": page_no,
                                       "coordinates": {"x_points": round(float(rect.x0), 2),
                                                       "y_points": round(float(rect.y0), 2),
                                                       "width_points": round(width, 2),
                                                       "height_points": round(height, 2)},
                                       "rotation_degrees": 0.0,
                                       "display_aspect_ratio": width / height if height else None})
                        if len(assets) >= max_assets:
                            return assets
            return assets
        finally:
            document.close()
    return []


def _perceptual_hash(image_bytes: bytes) -> tuple[int, float]:
    """Small dependency-free DCT perceptual hash and source aspect ratio."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            if opened.width * opened.height > 40_000_000:
                raise ValueError("Image exceeds the visual analysis pixel limit")
            opened.load()
            rgba = ImageOps.exif_transpose(opened).convert("RGBA")
            aspect = rgba.width / rgba.height if rgba.height else 1.0
            background = Image.new("RGBA", rgba.size, "white")
            image = Image.alpha_composite(background, rgba).convert("L").resize((32, 32), Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Unsupported or unreadable logo image") from exc
    pixels = list(image.tobytes())
    size = 32
    basis = [[math.cos((2 * x + 1) * u * math.pi / (2 * size)) for x in range(size)] for u in range(8)]
    row_coeffs = [[sum(pixels[y * size + x] * basis[u][x] for x in range(size)) for u in range(8)]
                  for y in range(size)]
    coefficients = []
    for v in range(8):
        for u in range(8):
            value = sum(row_coeffs[y][u] * basis[v][y] for y in range(size))
            if (u, v) != (0, 0):
                coefficients.append(value)
    ordered = sorted(coefficients)
    median = ordered[len(ordered) // 2]
    bits = 0
    for value in coefficients:
        bits = (bits << 1) | int(value > median)
    return bits, aspect


def _visual_thumbnail(image_bytes: bytes) -> str | None:
    """Small, content-bounded preview used for side-by-side human review."""
    from PIL import Image, ImageOps
    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            if opened.width * opened.height > 40_000_000:
                return None
            opened.load()
            image = ImageOps.exif_transpose(opened).convert("RGBA")
            background = Image.new("RGBA", image.size, "white")
            background.alpha_composite(image)
            image = background.convert("RGB")
            image.thumbnail((160, 120), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=62, optimize=True)
            return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")
    except Exception:
        return None


def _candidate_logo_hashes(image_bytes: bytes) -> tuple[list[tuple[int, int, bool]], float]:
    """Hash original, right-angle rotated, and mirrored candidates for misuse review."""
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(image_bytes)) as opened:
        if opened.width * opened.height > 40_000_000:
            raise ValueError("Image exceeds the visual analysis pixel limit")
        opened.load()
        image = ImageOps.exif_transpose(opened).convert("RGBA")
    aspect = image.width / image.height if image.height else 1.0
    hashes = []
    for angle in (0, 90, 180, 270):
        rotated = image.rotate(angle, expand=True) if angle else image
        for mirrored in (False, True):
            candidate = ImageOps.mirror(rotated) if mirrored else rotated
            encoded = io.BytesIO()
            candidate.save(encoded, format="PNG")
            bits, _ = _perceptual_hash(encoded.getvalue())
            hashes.append((bits, angle, mirrored))
    return hashes, aspect


def analyze_logo_references(visual_assets: list[dict], approved_logos: list[dict], *,
                           max_hamming_distance: int = 7, aspect_tolerance: float = 0.12) -> dict:
    """Match embedded raster assets to approved logos; all matches need human review.

    Perceptual hashes tolerate resampling and common image recompression. They do
    not prove logo ownership or detect logos baked into page-background images.
    """
    if not 0 <= max_hamming_distance <= 32:
        raise ValueError("Logo similarity tolerance must be between 0 and 32 hash bits")
    if not 0 <= aspect_tolerance <= 1:
        raise ValueError("Logo aspect-ratio tolerance must be between 0 and 1")
    if not approved_logos:
        return {"status": "unavailable", "message": "No approved logo references are configured.",
                "matches": [], "assets_examined": 0, "limitations": [
                    "A page-composite logo, vector-only logo, or logo not stored as a separate raster object is not analyzed."]}
    references = []
    for logo in approved_logos:
        try:
            bits, aspect = _perceptual_hash(logo["image_bytes"])
            references.append({**logo, "hash": bits, "aspect": aspect})
        except (ValueError, KeyError):
            continue
    if not references:
        return {"status": "unavailable", "message": "Approved logo references could not be decoded.",
                "matches": [], "assets_examined": 0, "limitations": [
                    "No usable approved logo raster was available for comparison."]}
    matches = []
    examined = 0
    for asset in visual_assets[:80]:
        try:
            candidate_hashes, asset_aspect = _candidate_logo_hashes(asset["image_bytes"])
        except (ValueError, KeyError):
            continue
        examined += 1
        ranked = [((candidate_hash ^ ref["hash"]).bit_count(), ref, angle, mirrored)
                  for candidate_hash, angle, mirrored in candidate_hashes for ref in references]
        ranked.sort(key=lambda item: item[0])
        suspected_logo = "logo" in str(asset.get("label", "")).lower()
        if not ranked or (ranked[0][0] > max_hamming_distance and not suspected_logo):
            continue
        distance, reference, bitmap_rotation, mirrored = ranked[0] if ranked[0][0] <= max_hamming_distance else (None, None, 0, False)
        if reference is None:
            matches.append({"status": "unrecognized_logo_candidate", "review_status": "needs_human_review",
                            "asset_label": asset.get("label"), "page_number": asset.get("page_number"),
                            "coordinates": asset.get("coordinates"),
                            "submitted_preview": _visual_thumbnail(asset["image_bytes"]), "message":
                                "This image is labelled as a logo but does not closely match an approved reference."})
            continue
        display_aspect = asset.get("display_aspect_ratio") or asset_aspect
        shape_distortion = abs(display_aspect / reference["aspect"] - 1) > aspect_tolerance
        bitmap_distortion = abs(asset_aspect / reference["aspect"] - 1) > aspect_tolerance
        rotation = float(asset.get("rotation_degrees") or 0) % 360
        issues = []
        if shape_distortion or bitmap_distortion:
            issues.append("aspect_ratio_mismatch")
        if min(rotation, 360 - rotation) > 1:
            issues.append("rotated_placement")
        if bitmap_rotation:
            issues.append("rotated_raster_content")
        if mirrored:
            issues.append("mirrored_raster_content")
        matches.append({"status": "similar_to_approved_logo", "review_status": "needs_human_review",
                        "asset_label": asset.get("label"), "asset_kind": asset.get("kind"),
                        "page_number": asset.get("page_number"), "coordinates": asset.get("coordinates"),
                        "reference_asset_id": str(reference.get("id", "")),
                        "reference_name": reference.get("name", "Approved logo"),
                        "submitted_preview": _visual_thumbnail(asset["image_bytes"]),
                        "approved_preview": _visual_thumbnail(reference["image_bytes"]),
                        "perceptual_hash_distance": distance,
                        "similarity": round(1 - distance / 64, 3),
                        "issues": issues, "rotation_degrees": rotation,
                        "bitmap_rotation_degrees": bitmap_rotation, "mirrored": mirrored})
    return {"status": "partial", "method": "64-bit perceptual hash with embedded-image geometry checks",
            "max_hamming_distance": max_hamming_distance, "aspect_tolerance": aspect_tolerance,
            "assets_examined": examined, "matches": matches,
            "limitations": ["Perceptual similarity is a candidate match, not proof of logo identity or authorization.",
                            "Raster images baked into page backgrounds and vector-only logos are not identified as separate assets.",
                            "Unlabelled unmatched images are not assumed to be logos; misuse detection is therefore incomplete."]}


def analyze_document_typography_layout(document_bytes: bytes, source_type: str, *,
                                       approved_fonts: list[str] | None = None,
                                       min_font_size_pt: float | None = None,
                                       max_font_size_pt: float | None = None,
                                       min_margin_inches: float | None = None) -> dict:
    """Inspect extractable PDF/DOCX/PPTX text styles and page/slide bounds.

    Only checks explicit configured font and margin rules. Theme-inherited fonts,
    kerning, visual hierarchy, and semantic layout intent remain unknown.
    """
    source_type = source_type.lower()
    allowed_fonts = {_normalize_font_family(font) for font in (approved_fonts or []) if font.strip()}
    typography_configured = bool(allowed_fonts or min_font_size_pt is not None or max_font_size_pt is not None)
    layout_supported = source_type in ("pptx", "pdf")
    layout_configured = min_margin_inches is not None and layout_supported
    if min_font_size_pt is not None and min_font_size_pt < 0:
        raise ValueError("Minimum font size cannot be negative")
    if max_font_size_pt is not None and max_font_size_pt <= 0:
        raise ValueError("Maximum font size must be positive")
    if min_font_size_pt is not None and max_font_size_pt is not None and min_font_size_pt > max_font_size_pt:
        raise ValueError("Minimum font size cannot exceed maximum font size")
    if min_margin_inches is not None and not 0 <= min_margin_inches <= 5:
        raise ValueError("Minimum margin must be between 0 and 5 inches")

    text_items: list[dict] = []
    containers: list[dict] = []
    try:
        if source_type == "pptx":
            from pptx import Presentation
            presentation = Presentation(io.BytesIO(document_bytes))
            slide_w, slide_h = presentation.slide_width / 914400, presentation.slide_height / 914400
            for slide_no, slide in enumerate(presentation.slides, 1):
                for shape in slide.shapes:
                    left, top = shape.left / 914400, shape.top / 914400
                    width, height = shape.width / 914400, shape.height / 914400
                    containers.append({"page_number": slide_no, "coordinates": {
                        "x_inches": round(left, 3), "y_inches": round(top, 3),
                        "width_inches": round(width, 3), "height_inches": round(height, 3)},
                        "bounds": (left, top, left + width, top + height, slide_w, slide_h), "kind": "slide"})
                    if not getattr(shape, "has_text_frame", False):
                        continue
                    for paragraph in shape.text_frame.paragraphs:
                        for run in paragraph.runs:
                            if not run.text.strip():
                                continue
                            size = run.font.size.pt if run.font.size else None
                            text_items.append({"font": run.font.name, "size_pt": size,
                                               "page_number": slide_no,
                                               "coordinates": {"x_inches": round(left, 3), "y_inches": round(top, 3),
                                                               "width_inches": round(width, 3), "height_inches": round(height, 3)},
                                               "kind": "slide"})
        elif source_type == "pdf":
            import pymupdf
            document = pymupdf.open(stream=document_bytes, filetype="pdf")
            try:
                for page_no, page in enumerate(document, 1):
                    page_w, page_h = page.rect.width / 72, page.rect.height / 72
                    for block in page.get_text("dict").get("blocks", []):
                        if "lines" not in block:
                            continue
                        for line in block["lines"]:
                            for span in line["spans"]:
                                if not span.get("text", "").strip():
                                    continue
                                x0, y0, x1, y1 = span["bbox"]
                                coords = {"x_points": round(x0, 2), "y_points": round(y0, 2),
                                          "width_points": round(x1 - x0, 2), "height_points": round(y1 - y0, 2)}
                                text_items.append({"font": span.get("font"), "size_pt": float(span.get("size", 0)),
                                                   "page_number": page_no, "coordinates": coords, "kind": "page"})
                                containers.append({"page_number": page_no, "coordinates": coords,
                                                   "bounds": (x0 / 72, y0 / 72, x1 / 72, y1 / 72, page_w, page_h),
                                                   "kind": "page"})
            finally:
                document.close()
        elif source_type == "docx":
            from docx import Document
            document = Document(io.BytesIO(document_bytes))
            for paragraph_no, paragraph in enumerate(document.paragraphs, 1):
                for run in paragraph.runs:
                    if run.text.strip():
                        text_items.append({"font": run.font.name, "size_pt": run.font.size.pt if run.font.size else None,
                                           "page_number": None, "coordinates": {"paragraph": paragraph_no},
                                           "kind": "paragraph"})
        else:
            return {"typography": {"status": "unavailable", "message": "Typography extraction is not supported for this format.",
                                   "fonts_detected": [], "findings": []},
                    "layout": {"status": "unavailable", "message": "Layout extraction is not supported for this format.", "findings": []}}
    except Exception as exc:
        raise ValueError(f"Typography or layout extraction failed ({type(exc).__name__})") from exc

    typography_findings = []
    observed_fonts = sorted({str(item["font"]).strip() for item in text_items if item.get("font")})
    unknown_fonts = sum(1 for item in text_items if not item.get("font"))
    if typography_configured:
        for item in text_items:
            font = str(item.get("font") or "").strip()
            size = item.get("size_pt")
            reasons = []
            if allowed_fonts and font and _normalize_font_family(font) not in allowed_fonts:
                reasons.append(f"font family {font} is not in the approved list")
            if min_font_size_pt is not None and size is not None and size < min_font_size_pt:
                reasons.append(f"font size {size:g} pt is below the configured {min_font_size_pt:g} pt minimum")
            if max_font_size_pt is not None and size is not None and size > max_font_size_pt:
                reasons.append(f"font size {size:g} pt exceeds the configured {max_font_size_pt:g} pt maximum")
            if reasons:
                typography_findings.append({"page_number": item["page_number"], "kind": item["kind"],
                                            "coordinates": item["coordinates"], "font": font or None,
                                            "size_pt": size, "message": "; ".join(reasons),
                                            "review_status": "needs_human_review"})
    layout_findings = []
    if layout_configured:
        for item in containers:
            x0, y0, x1, y1, page_w, page_h = item["bounds"]
            margin = min_margin_inches
            if x0 < margin or y0 < margin or x1 > page_w - margin or y1 > page_h - margin:
                layout_findings.append({"page_number": item["page_number"], "kind": item["kind"],
                                        "coordinates": item["coordinates"],
                                        "message": f"Content is within less than the configured {margin:g} inch page/slide margin.",
                                        "review_status": "needs_human_review"})
    return {
        "typography": {"status": "partial" if typography_configured else "unavailable",
                       "message": ("Configured font-family and size checks were applied; inherited/theme fonts may be unknown."
                                   if typography_configured else "Set approved font families or font-size bounds to enable typography checks."),
                       "approved_fonts": sorted(allowed_fonts), "min_font_size_pt": min_font_size_pt,
                       "max_font_size_pt": max_font_size_pt, "fonts_detected": observed_fonts,
                       "unknown_font_count": unknown_fonts, "text_runs_analyzed": len(text_items),
                       "findings": typography_findings,
                       "limitations": ["Font hierarchy, kerning, visual weight, and theme-inherited fonts are not reliably assessed."]},
        "layout": {"status": "partial" if layout_configured else "unavailable",
                   "message": ("Configured page/slide margin checks were applied; candidates require visual review."
                               if layout_configured else "Set a minimum page/slide margin for PDF/PPTX layout-boundary checks."),
                   "min_margin_inches": min_margin_inches, "elements_analyzed": len(containers),
                   "findings": layout_findings,
                   "limitations": ["Alignment, spacing intent, overlap, and semantic placement are not inferred."]},
    }


def _rgb(value: str) -> tuple[int, int, int]:
    raw = value.strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        raise ValueError("Palette colors must be six digit hex values")
    return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    def linear(v: int) -> float:
        x = v / 255
        return ((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92
    r, g, b = map(linear, rgb)
    x = (r * 0.4124564 + g * 0.3575761 + b * 0.1804375) / 0.95047
    y = (r * 0.2126729 + g * 0.7151522 + b * 0.0721750)
    z = (r * 0.0193339 + g * 0.1191920 + b * 0.9503041) / 1.08883
    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _delta_e(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = _lab(a), _lab(b)
    return sum((x - y) ** 2 for x, y in zip(la, lb)) ** 0.5


def analyze_palette(image_bytes: bytes, approved_colors: list[str], *, delta_threshold: float = 18.0,
                    coverage_threshold: float = 0.12) -> dict:
    """Return dominant swatches and only material out-of-palette color candidates.

    This is a palette screening signal. It does not infer intent, distinguish photos
    from designed elements, or decide that a color is a violation by itself.
    """
    from PIL import Image, UnidentifiedImageError
    if not 0 <= delta_threshold <= 200:
        raise ValueError("Visual color tolerance must be between 0 and 200 Delta E")
    if not 0 <= coverage_threshold <= 1:
        raise ValueError("Visual color coverage threshold must be between 0 and 1")
    try:
        opened = Image.open(io.BytesIO(image_bytes))
        if opened.width * opened.height > 40_000_000:
            raise ValueError("Image exceeds the visual analysis pixel limit")
        opened.load()
        image = opened.convert("RGB")
        image.thumbnail((900, 900))
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Unsupported or unreadable image") from exc
    colors = [_rgb(c) for c in approved_colors]
    if not colors:
        return {"status": "unavailable", "message": "No approved brand palette is configured.",
                "dominant_colors": [], "findings": []}
    quantized = image.quantize(colors=32, method=Image.Quantize.MEDIANCUT)
    counts = quantized.getcolors(maxcolors=1_000_000) or []
    palette = quantized.getpalette() or []
    total = max(1, sum(count for count, _ in counts))
    ranked = sorted(counts, reverse=True)
    target_indices = {idx for _, idx in ranked[:8]}
    bounds = {}
    width, height = quantized.size
    for offset, idx in enumerate(quantized.tobytes()):
        if idx not in target_indices:
            continue
        x, y = offset % width, offset // width
        box = bounds.setdefault(idx, [width, height, -1, -1])
        box[0], box[1], box[2], box[3] = min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y)
    findings: list[PaletteFinding] = []
    swatches = []
    for count, idx in ranked[:8]:
        rgb = tuple(palette[idx * 3:idx * 3 + 3])
        if len(rgb) != 3:
            continue
        nearest, distance = min(((candidate, _delta_e(rgb, candidate)) for candidate in colors), key=lambda x: x[1])
        coverage = count / total
        swatches.append({"color": "#%02X%02X%02X" % rgb, "coverage": round(coverage, 4),
                         "nearest_approved": "#%02X%02X%02X" % nearest, "delta_e": round(distance, 1)})
        if distance > delta_threshold and coverage >= coverage_threshold:
            box = bounds.get(idx)
            coordinates = None
            if box and box[2] >= box[0] and box[3] >= box[1]:
                x0, y0, x1, y1 = box
                coordinates = {"x_pixels": x0, "y_pixels": y0, "width_pixels": x1 - x0 + 1,
                               "height_pixels": y1 - y0 + 1,
                               "x_percent": round(100 * x0 / width, 2),
                               "y_percent": round(100 * y0 / height, 2),
                               "width_percent": round(100 * (x1 - x0 + 1) / width, 2),
                               "height_percent": round(100 * (y1 - y0 + 1) / height, 2)}
            findings.append({**PaletteFinding("#%02X%02X%02X" % rgb, "#%02X%02X%02X" % nearest,
                                              round(distance, 1), round(coverage, 4)).__dict__,
                             "coordinates": coordinates})
    return {"status": "completed", "method": "CIE76 dominant-color distance", "dominant_colors": swatches,
            "delta_threshold": delta_threshold, "coverage_threshold": coverage_threshold,
            "findings": findings, "limitations": [
                "Photographs, gradients, shadows, and antialiasing can introduce colors outside the approved palette.",
                "This analysis does not verify logos, typography, or layout."]}

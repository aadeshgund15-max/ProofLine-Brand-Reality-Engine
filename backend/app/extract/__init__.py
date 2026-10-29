"""Content extraction for every supported input type.

Each extractor returns an ExtractionResult with:
  * status      complete | partial | empty | unsupported | failed
  * text        the extracted snapshot (what reviews run against)
  * segments    character ranges mapped to a location (page / slide / paragraph / OCR line / url)
  * warnings    human-readable limitations
  * quality     extractor-specific metrics (e.g. OCR confidence)

File types are detected from content (magic bytes / archive structure), not from the
filename extension alone. Anything that is not clearly extracted in full is NOT 'complete'.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Optional

SUPPORTED_TYPES = ("text", "docx", "pdf", "image", "pptx", "url")
MAX_PDF_PAGES = 300
MAX_SLIDES = 300
MAX_IMAGE_PIXELS = 40_000_000
MIN_PDF_TEXT_CHARS = 20


@dataclass
class Segment:
    start: int
    end: int
    label: str
    kind: str  # paragraph | table | page | slide | ocr_line | url | text

    def as_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "label": self.label, "kind": self.kind}


@dataclass
class ExtractionResult:
    source_type: str
    status: str
    text: str = ""
    segments: list[Segment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    quality: dict = field(default_factory=dict)

    def location_at(self, offset: Optional[int]) -> Optional[dict]:
        return locate(self.segments, offset)


def locate(segments, offset: Optional[int]) -> Optional[dict]:
    """Return {'label','kind'} of the segment containing a character offset."""
    if offset is None:
        return None
    for s in segments:
        start, end = (s.start, s.end) if isinstance(s, Segment) else (s["start"], s["end"])
        if start <= offset < end:
            label, kind = (s.label, s.kind) if isinstance(s, Segment) else (s["label"], s["kind"])
            return {"label": label, "kind": kind}
    return None


class _Builder:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.segments: list[Segment] = []
        self.pos = 0

    def add(self, text: str, label: str, kind: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.parts:
            self.parts.append("\n")
            self.pos += 1
        self.parts.append(text)
        self.segments.append(Segment(self.pos, self.pos + len(text), label, kind))
        self.pos += len(text)

    @property
    def text(self) -> str:
        return "".join(self.parts)


def _result(kind: str, b: _Builder, warnings: list[str], quality: dict,
            partial: bool = False) -> ExtractionResult:
    text = b.text
    if not text.strip():
        return ExtractionResult(kind, "empty", "", [], warnings or ["No text could be extracted."], quality)
    return ExtractionResult(kind, "partial" if partial else "complete", text, b.segments, warnings, quality)


def _failed(kind: str, msg: str) -> ExtractionResult:
    return ExtractionResult(kind, "failed", "", [], [msg], {})


# ------------------------------------------------------------ detection
def sniff(data: bytes, filename: str = "") -> Optional[str]:
    """Detect the content type from bytes. Plain text is accepted only with a .txt name."""
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        try:
            names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
        except zipfile.BadZipFile:
            return None
        if "word/document.xml" in names:
            return "docx"
        if "ppt/presentation.xml" in names:
            return "pptx"
        return None
    if (data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff" or data[:2] == b"BM"
            or data[:4] in (b"II*\x00", b"MM\x00*") or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")):
        return "image"
    if filename.lower().endswith(".txt"):
        try:
            data.decode("utf-8")
            return "text"
        except UnicodeDecodeError:
            return None
    return None


def validate_upload(data: bytes, filename: str, max_bytes: int) -> tuple[Optional[str], Optional[str]]:
    """Returns (detected_type, error). Error is a user-facing message or None."""
    if len(data) == 0:
        return None, "The file is empty."
    if len(data) > max_bytes:
        return None, f"The file is larger than the {max_bytes // (1024 * 1024)} MB limit."
    kind = sniff(data, filename)
    if kind is None and data[:4] == b"PK\x03\x04":
        try:
            zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return None, "The file appears to be corrupted (it is not a valid DOCX/PPTX archive)."
    if kind is None:
        return None, ("Unsupported or unrecognised file. Supported: TXT, DOCX, text-based PDF, PPTX, "
                      "PNG/JPEG/BMP/TIFF/WEBP images.")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    expected = {"text": {"txt"}, "docx": {"docx"}, "pdf": {"pdf"}, "pptx": {"pptx"},
                "image": {"png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp"}}[kind]
    if ext and ext not in expected:
        return None, f"The file extension .{ext} does not match its content ({kind})."
    return kind, None


# ----------------------------------------------------------------- text
def extract_text(raw: str, max_chars: int = 500_000) -> ExtractionResult:
    text = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ExtractionResult("text", "empty", "", [], ["No text was provided."], {})
    warnings: list[str] = []
    partial = False
    if len(text) > max_chars:
        text, partial = text[:max_chars], True
        warnings.append(f"Text was truncated to {max_chars} characters.")
    b = _Builder()
    for i, para in enumerate([p for p in re.split(r"\n\s*\n|\n", text) if p.strip()], 1):
        b.add(para, f"Paragraph {i}", "paragraph")
    return _result("text", b, warnings, {"characters": len(text)}, partial)


# ----------------------------------------------------------------- docx
def extract_docx(data: bytes) -> ExtractionResult:
    try:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        document = docx.Document(io.BytesIO(data))
    except Exception as e:  # corrupted / not a real docx
        return _failed("docx", f"The DOCX file could not be opened ({type(e).__name__}).")
    b = _Builder()
    warnings: list[str] = []
    p_no = t_no = 0
    try:
        for child in document.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                para = Paragraph(child, document)
                if para.text.strip():
                    p_no += 1
                    b.add(para.text, f"Paragraph {p_no}", "paragraph")
            elif tag == "tbl":
                t_no += 1
                table = Table(child, document)
                for r_no, row in enumerate(table.rows, 1):
                    seen, cells = set(), []
                    for c in row.cells:
                        if id(c._tc) in seen:
                            continue
                        seen.add(id(c._tc))
                        cells.append(c.text.strip().replace("\n", " "))
                    b.add(" | ".join(cells), f"Table {t_no}, row {r_no}", "table")
    except Exception as e:
        return _failed("docx", f"The DOCX content could not be read ({type(e).__name__}).")
    has_images = any("image" in r.reltype for r in document.part.rels.values())
    partial = False
    if has_images:
        partial = True
        warnings.append("The document contains images; any text inside images was not extracted.")
    for part in document.sections:
        if any(p.text.strip() for p in part.header.paragraphs + part.footer.paragraphs):
            warnings.append("Headers/footers are not included in the extracted text.")
            break
    return _result("docx", b, warnings, {"paragraphs": p_no, "tables": t_no}, partial)


# ------------------------------------------------------------------ pdf
def extract_pdf(data: bytes) -> ExtractionResult:
    pages: list[str] = []
    try:
        try:
            import fitz  # PyMuPDF (preferred)
            doc = fitz.open(stream=data, filetype="pdf")
            if doc.needs_pass:
                return _failed("pdf", "The PDF is password protected.")
            n = doc.page_count
            for i in range(min(n, MAX_PDF_PAGES)):
                pages.append(doc.load_page(i).get_text("text"))
            engine = "pymupdf"
        except ImportError:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                return _failed("pdf", "The PDF is password protected.")
            n = len(reader.pages)
            for i in range(min(n, MAX_PDF_PAGES)):
                pages.append(reader.pages[i].extract_text() or "")
            engine = "pypdf"
    except Exception as e:
        return _failed("pdf", f"The PDF could not be read ({type(e).__name__}); it may be corrupted.")
    b = _Builder()
    empty_pages: list[int] = []
    for i, t in enumerate(pages, 1):
        if t.strip():
            b.add(t, f"Page {i}", "page")
        else:
            empty_pages.append(i)
    warnings: list[str] = []
    quality = {"pages": n, "pages_with_text": n - len(empty_pages) if n <= MAX_PDF_PAGES else None,
               "engine": engine}
    if len(b.text.strip()) < MIN_PDF_TEXT_CHARS:
        return ExtractionResult("pdf", "empty", "", [], [
            "No selectable text was found. This looks like a scanned or image-only PDF; "
            "OCR would be required and is not applied to PDFs."], quality)
    partial = False
    if empty_pages:
        partial = True
        shown = ", ".join(map(str, empty_pages[:10])) + ("…" if len(empty_pages) > 10 else "")
        warnings.append(f"No text found on page(s) {shown}; they may be scanned images.")
    if n > MAX_PDF_PAGES:
        partial = True
        warnings.append(f"Only the first {MAX_PDF_PAGES} of {n} pages were processed.")
    return _result("pdf", b, warnings, quality, partial)


# ----------------------------------------------------------------- pptx
def extract_pptx(data: bytes) -> ExtractionResult:
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        prs = Presentation(io.BytesIO(data))
    except Exception as e:
        return _failed("pptx", f"The PPTX file could not be opened ({type(e).__name__}).")

    def walk(shapes):
        for sh in shapes:
            if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                yield from walk(sh.shapes)
            else:
                yield sh

    b = _Builder()
    warnings: list[str] = []
    picture_slides: list[int] = []
    n_slides = 0
    try:
        for i, slide in enumerate(prs.slides, 1):
            n_slides = i
            if i > MAX_SLIDES:
                warnings.append(f"Only the first {MAX_SLIDES} slides were processed.")
                break
            chunks: list[str] = []
            for sh in walk(slide.shapes):
                if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    picture_slides.append(i)
                if getattr(sh, "has_text_frame", False) and sh.has_text_frame:
                    for para in sh.text_frame.paragraphs:
                        t = "".join(r.text for r in para.runs).strip()
                        if t:
                            chunks.append(t)
                if getattr(sh, "has_table", False) and sh.has_table:
                    for row in sh.table.rows:
                        chunks.append(" | ".join(c.text.strip().replace("\n", " ") for c in row.cells))
            b.add("\n".join(chunks), f"Slide {i}", "slide")
    except Exception as e:
        return _failed("pptx", f"The PPTX content could not be read ({type(e).__name__}).")
    partial = bool(picture_slides) or n_slides > MAX_SLIDES
    if picture_slides:
        uniq = sorted(set(picture_slides))
        warnings.append("Slide(s) " + ", ".join(map(str, uniq[:10])) +
                        " contain pictures; text inside pictures was not extracted.")
    warnings.append("Speaker notes are not extracted.")
    return _result("pptx", b, warnings, {"slides": n_slides}, partial)


# ---------------------------------------------------------------- image
def extract_image(data: bytes, ocr_lang: str = "eng", min_confidence: float = 70.0) -> ExtractionResult:
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:
        return _failed("image", f"The image could not be opened ({type(e).__name__}).")
    try:
        import pytesseract
        d = pytesseract.image_to_data(img.convert("RGB"), lang=ocr_lang, output_type=pytesseract.Output.DICT,
                                      timeout=60)
    except Exception as e:
        name = type(e).__name__
        msg = ("OCR is not available on the server (Tesseract is not installed)."
               if name == "TesseractNotFoundError" else f"OCR failed ({name}).")
        return _failed("image", msg)
    lines: dict[tuple, list[tuple[str, float, int, int]]] = {}
    for i, word in enumerate(d["text"]):
        word = (word or "").strip()
        try:
            conf = float(d["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if not word or conf < 0:
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        lines.setdefault(key, []).append((word, conf, d["left"][i], d["top"][i]))
    b = _Builder()
    confs: list[float] = []
    low_words = 0
    for n, key in enumerate(sorted(lines), 1):
        words = lines[key]
        confs.extend(c for _, c, _, _ in words)
        low_words += sum(1 for _, c, _, _ in words if c < min_confidence)
        b.add(" ".join(w for w, _, _, _ in words), f"OCR line {n} (x={words[0][2]}, y={words[0][3]})", "ocr_line")
    quality = {
        "word_count": len(confs),
        "mean_confidence": round(sum(confs) / len(confs), 1) if confs else None,
        "low_confidence_words": low_words,
        "image_size": list(img.size),
    }
    warnings = ["Text was read by OCR and may contain recognition errors; findings from OCR text are "
                "not definitive."]
    partial = False
    if confs and (quality["mean_confidence"] < min_confidence or low_words / len(confs) > 0.2):
        partial = True
        warnings.append(f"OCR confidence is low (mean {quality['mean_confidence']}%); "
                        f"{low_words} of {len(confs)} words are uncertain.")
    return _result("image", b, warnings, quality, partial)


# ----------------------------------------------------------------- html
_DROP_TAGS = ["script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form",
              "iframe", "template", "canvas"]


def extract_html(html: bytes | str, url: str, truncated: bool = False) -> ExtractionResult:
    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as e:
        return _failed("url", f"The page could not be parsed ({type(e).__name__}).")
    title = soup.title.get_text(strip=True) if soup.title else ""
    for t in soup(_DROP_TAGS):
        t.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    b = _Builder()
    if title:
        b.add(title, f"Page title ({url})", "url")
    n = 0
    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th", "blockquote", "figcaption"]):
        if el.find(["p", "li", "h1", "h2", "h3", "h4", "td", "th"]):
            continue  # container; its children are visited individually
        txt = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if txt:
            n += 1
            b.add(txt, f"{el.name.upper()} block {n} ({url})", "url")
    warnings: list[str] = []
    partial = truncated
    if truncated:
        warnings.append("The page was larger than the size limit and was cut off.")
    if len(b.text) < 200:
        partial = True
        warnings.append("Very little text was found. The page may render its content with JavaScript, "
                        "which is not executed.")
    return _result("url", b, warnings, {"title": title, "blocks": n}, partial)


def extract_file(kind: str, data: bytes) -> ExtractionResult:
    if kind == "text":
        return extract_text(data.decode("utf-8", "replace"))
    if kind == "docx":
        return extract_docx(data)
    if kind == "pdf":
        return extract_pdf(data)
    if kind == "pptx":
        return extract_pptx(data)
    if kind == "image":
        return extract_image(data)
    return ExtractionResult(kind, "unsupported", "", [], [f"Unsupported type: {kind}"], {})

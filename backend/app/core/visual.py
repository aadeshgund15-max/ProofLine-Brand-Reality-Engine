"""Conservative image palette analysis using CIE Lab (Delta E 1976)."""
from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class PaletteFinding:
    color: str
    nearest_approved: str
    delta_e: float
    coverage: float


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
        if distance >= delta_threshold and coverage >= coverage_threshold:
            findings.append(PaletteFinding("#%02X%02X%02X" % rgb, "#%02X%02X%02X" % nearest,
                                           round(distance, 1), round(coverage, 4)))
    return {"status": "completed", "method": "CIE76 dominant-color distance", "dominant_colors": swatches,
            "findings": [f.__dict__ for f in findings], "limitations": [
                "Photographs, gradients, shadows, and antialiasing can introduce colors outside the approved palette.",
                "This analysis does not verify logos, typography, or layout."]}

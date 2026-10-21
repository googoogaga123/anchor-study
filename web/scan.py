"""Scanning printed pages with a phone: straighten each photo, check it can be read,
and put the pages together as one PDF. Everything here runs on this server, free.

  crop_page     find the page's four corners in the photo (OpenCV) and straighten
                it; when no page outline is found, keep the photo as taken
  readability   a quick check before the student saves: how many lines of text
                the OCR detector finds, and how sharp the photo is. It does not
                read the words - Docling does that after Save (ingest.py)
  assemble_pdf  the pages, in order, as one PDF the size of A4 at 200 dpi

Measured 20 Oct 2026 on the IS114 PDF rendered to a 10-page image-only PDF:
Docling's own OCR (RapidOCR, already installed) brought back 1,921 of the
1,989 words of the original text layer, kept both tables' rows (15 of 15,
4 of 4) and the page numbers, at 8.5 s per page. The readability thresholds
come from blurring one of those pages: sharp, 122 text lines found and a
sharpness of 4,005; lightly blurred, 121 lines and 94 (still read well);
heavily blurred, 2 lines and 7.
"""
import io
import threading

import cv2
import numpy as np
from PIL import Image, ImageOps

LONG_SIDE = 2400      # pixels kept per page (about 200 dpi on A4)
DETECT_SIDE = 1000    # the copy the page outline is looked for in
MIN_PAGE_AREA = 0.25  # a page outline must cover at least this much of the photo
A4_LONG = 2339        # A4's long side at 200 dpi
PDF_DPI = 200
MIN_LINES = 3         # fewer text lines found -> "no text found"
MIN_SHARPNESS = 40    # below this (at 1400 px) -> "looks blurry"

_detector, _detector_lock = None, threading.Lock()  # one OCR detector, used one page at a time


def _decode(data):
    """A photo as an RGB array, turned upright by its EXIF rotation."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    return np.asarray(img)


def _encode(rgb, quality=85):
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()  # re-encoded: no EXIF, so no location data


def _fit(rgb, side):
    h, w = rgb.shape[:2]
    s = side / max(h, w)
    return rgb if s >= 1 else cv2.resize(rgb, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)


def _order(pts):
    """Corners as top-left, top-right, bottom-right, bottom-left."""
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], dtype=np.float32)


def find_page(rgb):
    """The page's four corners in full-photo pixels, or None when no outline is clear."""
    small = _fit(rgb, DETECT_SIDE)
    scale = rgb.shape[1] / small.shape[1]
    grey = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), (5, 5), 0)
    area = small.shape[0] * small.shape[1]
    med = float(np.median(grey))
    for lo, hi in ((int(max(0, 0.66 * med)), int(min(255, 1.33 * med))), (30, 100), (75, 200)):
        edges = cv2.dilate(cv2.Canny(grey, lo, hi), np.ones((3, 3), np.uint8), iterations=2)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
            if cv2.contourArea(c) < MIN_PAGE_AREA * area:
                break
            hull = cv2.convexHull(c)
            approx = cv2.approxPolyDP(hull, 0.02 * cv2.arcLength(hull, True), True)
            if len(approx) == 4:
                return _order(approx.reshape(4, 2).astype(np.float32) * scale)
    return None


def crop_page(data):
    """(page JPEG, cropped?) for one photo: straightened when its outline is found."""
    rgb = _decode(data)
    quad = find_page(rgb)
    if quad is not None:
        tl, tr, br, bl = quad
        w = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
        h = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
        dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
        rgb = cv2.warpPerspective(rgb, cv2.getPerspectiveTransform(quad, dst), (w, h), flags=cv2.INTER_CUBIC)
    rgb = _fit(rgb, LONG_SIDE)
    # Mild contrast only (no black-and-white thresholding, which can cost OCR words).
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    lab[:, :, 0] = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(lab[:, :, 0])
    return _encode(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)), quad is not None


def readability(data):
    """{"lines", "sharpness", "ok", "why"} for a page JPEG (see the module docstring)."""
    global _detector
    rgb = _fit(_decode(data), 1400)
    sharpness = float(cv2.Laplacian(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), cv2.CV_64F).var())
    with _detector_lock:
        if _detector is None:
            from rapidocr import EngineType, RapidOCR
            _detector = RapidOCR(params={"Det.engine_type": EngineType.TORCH, "Cls.engine_type": EngineType.TORCH,
                                         "Rec.engine_type": EngineType.TORCH, "Global.log_level": "error"})
        found = _detector(rgb, use_cls=False, use_rec=False)
    lines = 0 if found.boxes is None else len(found.boxes)
    why = ("No text found - is the page in the photo?" if lines < MIN_LINES
           else "Looks blurry - hold still and retake?" if sharpness < MIN_SHARPNESS else None)
    return {"lines": lines, "sharpness": round(sharpness), "ok": why is None, "why": why}


def assemble_pdf(pages):
    """The page JPEGs, in order, as one PDF; every page scaled to A4's long side."""
    imgs = []
    for data in pages:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        s = A4_LONG / max(img.size)
        imgs.append(img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS))
    buf = io.BytesIO()
    imgs[0].save(buf, "PDF", save_all=True, append_images=imgs[1:], resolution=PDF_DPI)
    return buf.getvalue()

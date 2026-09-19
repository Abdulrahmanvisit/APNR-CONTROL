import os
import re

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

TESSERACT_CANDIDATES = (
    os.getenv("TESSERACT_CMD"),
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def _configure_tesseract():
    """Configure Tesseract from the environment or common Windows locations."""
    if pytesseract is None:
        return False
    for candidate in TESSERACT_CANDIDATES:
        if candidate and os.path.isfile(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            return True
    try:
        pytesseract.get_tesseract_version()
        return True
    except (OSError, RuntimeError):
        return False


def clean_plate_text(text):
    """Normalize OCR output to uppercase ASCII alphanumeric characters."""
    return re.sub(r"[^A-Z0-9]", "", str(text).upper())


def _preprocess(image):
    """Build contrast-enhanced and thresholded OCR candidates."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    filtered = cv2.bilateralFilter(enhanced, 9, 75, 75)
    adaptive = cv2.adaptiveThreshold(
        filtered, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
    )
    return gray, enhanced, adaptive


def _find_plate_crop(gray, enhanced):
    """Return the most plausible rectangular plate crop, if one is visible."""
    edges = cv2.Canny(enhanced, 50, 180)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    image_area = gray.shape[0] * gray.shape[1]
    candidates = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:30]:
        area = cv2.contourArea(contour)
        if area < image_area * 0.01:
            continue
        perimeter = cv2.arcLength(contour, True)
        approximation = cv2.approxPolyDP(contour, 0.03 * perimeter, True)
        x, y, width, height = cv2.boundingRect(approximation)
        ratio = width / max(height, 1)
        if len(approximation) == 4 and 2.0 <= ratio <= 7.0:
            candidates.append((area, gray[y:y + height, x:x + width]))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _ocr_candidates(image, crop):
    """Return the strongest OCR reading from full-frame and crop variants."""
    sources = [image] + ([crop] if crop is not None else [])
    readings = []
    for source in sources:
        gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY) if len(source.shape) == 3 else source
        scale = max(1.0, 1200 / max(gray.shape[1], 1))
        resized = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(resized)
        variants = (
            enhanced,
            cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
            cv2.adaptiveThreshold(
                enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
            ),
        )
        for variant in variants:
            for page_mode in (6, 7, 8, 11):
                data = pytesseract.image_to_data(
                    variant,
                    config=f"--psm {page_mode} --oem 3",
                    output_type=pytesseract.Output.DICT,
                )
                words = [text for text in data["text"] if text.strip()]
                text = clean_plate_text(" ".join(words))
                scores = [
                    float(value)
                    for value, word in zip(data["conf"], data["text"])
                    if word.strip() and float(value) >= 0
                ]
                confidence = sum(scores) / len(scores) if scores else 0.0
                if 5 <= len(text) <= 12 and any(character.isdigit() for character in text):
                    readings.append((confidence, len(text), text))
    return max(
        readings,
        key=lambda reading: (
            sum(character.isdigit() for character in reading[2]),
            reading[0],
            reading[1],
        ),
    ) if readings else None


def process_license_plate(image_path):
    """Run robust image preprocessing and Tesseract OCR on an image file."""
    if not os.path.isfile(image_path):
        return {"success": False, "plate_number": "", "confidence": 0.0, "error": "Image file not found."}
    if cv2 is None or pytesseract is None:
        return {
            "success": False,
            "plate_number": "OCR_ERROR",
            "confidence": 0.0,
            "error": "OCR dependencies are unavailable. Install opencv-python and pytesseract.",
        }
    if not _configure_tesseract():
        return {
            "success": False,
            "plate_number": "OCR_ERROR",
            "confidence": 0.0,
            "error": "Tesseract OCR executable was not found. Set TESSERACT_CMD or install Tesseract.",
        }

    image = cv2.imread(image_path)
    if image is None:
        return {"success": False, "plate_number": "", "confidence": 0.0, "error": "Failed to decode image."}

    try:
        gray, enhanced, adaptive = _preprocess(image)
        crop = _find_plate_crop(gray, enhanced)
        reading = _ocr_candidates(image, crop)
        plate_text = reading[2] if reading else ""
        confidence = min(99.0, round(reading[0], 1)) if reading else 0.0
    except (cv2.error, OSError, RuntimeError) as error:
        return {"success": False, "plate_number": "OCR_ERROR", "confidence": 0.0, "error": str(error)}

    return {
        "success": bool(plate_text),
        "plate_number": plate_text or "UNREADABLE",
        "confidence": confidence,
        "error": None if plate_text else "No plate text was detected.",
    }

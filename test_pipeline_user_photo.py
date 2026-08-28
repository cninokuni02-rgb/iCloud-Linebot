import io
import re
import requests
from PIL import Image, ImageEnhance
from checkers import ICloudChecker

def test_full_pipeline(image_path: str):
    image_bytes = open(image_path, "rb").read()
    
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.4)
    out = io.BytesIO()
    img.save(out, format='JPEG', quality=85)
    opt_bytes = out.getvalue()

    url = "https://api.ocr.space/parse/image"
    payload = {
        "apikey": "K88726514288957",
        "OCREngine": "2",
        "detectOrientation": True,
        "scale": True,
        "isTable": True
    }
    files = {"file": ("image.jpg", opt_bytes, "image/jpeg")}
    res = requests.post(url, data=payload, files=files, timeout=12)
    data = res.json()
    raw_text = data["ParsedResults"][0]["ParsedText"]

    # 1. Clean Slashed Zeros and Normalize
    normalized = raw_text.replace('Ø', '0').replace('ø', '0').replace('–', '-').replace('—', '-')

    # 2. Extract Device ID (IMEI or Serial Number)
    detected_id = None
    
    # Check 15-digit IMEI
    imeis = re.findall(r"\b\d{15}\b", normalized)
    if imeis:
        detected_id = imeis[0]
    else:
        for line in normalized.splitlines():
            digits = re.sub(r"[^\d]", "", line)
            if len(digits) == 15:
                detected_id = digits
                break

    # Check Serial Number (10-12 chars)
    if not detected_id:
        # Match alphanumeric strings of 10-12 length
        candidates = re.findall(r"\b([A-Z0-9]{10,12})\b", normalized)
        for c in candidates:
            # Must have both letters and digits and not be model number like MNQQ2THA
            if any(char.isdigit() for char in c) and any(char.isalpha() for char in c):
                if not any(k in c for k in ["MNQQ2", "IPHONE", "PLUS", "IOS", "ABOUT", "MODEL"]):
                    detected_id = c
                    break

    # Check Model Name in text
    detected_model = None
    model_match = re.search(r"iPhone\s+[0-9A-Za-z\s\+]+", normalized, re.IGNORECASE)
    if model_match:
        detected_model = "Apple " + model_match.group(0).strip()

    print(f"Extracted Device ID: {detected_id}")
    print(f"Extracted Model: {detected_model}")
    
    checker = ICloudChecker()
    result = checker.check(detected_id)
    if detected_model:
        result["model"] = detected_model
    print("Final Verification Result:", result)

test_full_pipeline("C:/Users/User/.gemini/antigravity/brain/d0080509-c4a3-4f88-b0cf-590d6d44eee9/.user_uploaded/media_1787912496674.jpg")

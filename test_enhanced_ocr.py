import io
import re
import requests
from PIL import Image, ImageEnhance, ImageFilter

def extract_imei_enhanced(image_bytes: bytes) -> str:
    # 1. Optimize Image
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    img.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.5)
    
    out = io.BytesIO()
    img.save(out, format='JPEG', quality=90)
    opt_bytes = out.getvalue()
    
    # Try Engine 2 first, then Engine 1
    for engine in ["2", "1"]:
        try:
            url = "https://api.ocr.space/parse/image"
            payload = {
                "apikey": "helloworld",
                "OCREngine": engine,
                "isOverlayRequired": False,
                "detectOrientation": True,
                "scale": True
            }
            files = {"file": ("image.jpg", opt_bytes, "image/jpeg")}
            res = requests.post(url, data=payload, files=files, timeout=20)
            if res.status_code == 200:
                data = res.json()
                parsed = data.get("ParsedResults", [])
                if parsed:
                    text = parsed[0].get("ParsedText", "")
                    
                    # Search continuous
                    imeis = re.findall(r"\b\d{15}\b", text)
                    if imeis:
                        return imeis[0]
                    
                    # Search spaced
                    for line in text.splitlines():
                        digits = re.sub(r"[^\d]", "", line)
                        if len(digits) == 15:
                            return digits
                        sub = re.findall(r"\d{15}", digits)
                        if sub:
                            return sub[0]
                    
                    # Replace OCR misreads near IMEI label
                    for line in text.splitlines():
                        if any(k in line.upper() for k in ["IMEI", "MEID", "SERIAL", "SN"]):
                            fixed = line.upper().replace('O', '0').replace('I', '1').replace('L', '1').replace('S', '5').replace('B', '8')
                            digits = re.sub(r"[^\d]", "", fixed)
                            if len(digits) == 15:
                                return digits
                            sub = re.findall(r"\d{15}", digits)
                            if sub:
                                return sub[0]
        except Exception as e:
            print(f"Engine {engine} error: {e}")
            
    return ""

print("Enhanced OCR tester ready")

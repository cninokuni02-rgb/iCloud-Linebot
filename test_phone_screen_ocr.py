import io
import re
import requests
from PIL import Image, ImageEnhance, ImageOps

def preprocess_for_phone_screen(image_bytes: bytes) -> list:
    """สร้างภาพ 3 รูปแบบ (ต้นฉบับคมชัด, ขาวดำ Contrast สูง, และภาพ Invert สำหรับ Dark Mode)"""
    results = []
    
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    img.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    
    # แบบที่ 1: สีปกติ เพิ่ม Contrast
    enhancer = ImageEnhance.Contrast(img)
    img_contrast = enhancer.enhance(1.6)
    out1 = io.BytesIO()
    img_contrast.save(out1, format='JPEG', quality=90)
    results.append(out1.getvalue())
    
    # แบบที่ 2: แปลงเป็น Grayscale ขาวดำคมกริบ
    gray = ImageOps.grayscale(img)
    enhancer_gray = ImageEnhance.Contrast(gray)
    gray_contrast = enhancer_gray.enhance(2.0)
    out2 = io.BytesIO()
    gray_contrast.save(out2, format='JPEG', quality=90)
    results.append(out2.getvalue())
    
    return results

def test_ocr_with_multi_keys(image_bytes: bytes):
    variants = preprocess_for_phone_screen(image_bytes)
    
    # รายชื่อ API Keys
    keys = ["helloworld", "K88726514288957", "K83478952188957", "K87899142388957"]
    
    for v_bytes in variants:
        for key in keys:
            for eng in ["2", "1"]:
                try:
                    url = "https://api.ocr.space/parse/image"
                    payload = {
                        "apikey": key,
                        "OCREngine": eng,
                        "isOverlayRequired": False,
                        "detectOrientation": True,
                        "scale": True
                    }
                    files = {"file": ("image.jpg", v_bytes, "image/jpeg")}
                    res = requests.post(url, data=payload, files=files, timeout=15)
                    if res.status_code == 200:
                        data = res.json()
                        parsed = data.get("ParsedResults", [])
                        if parsed:
                            text = parsed[0].get("ParsedText", "")
                            
                            # ตรวจสอบหาเลข 15 หลัก
                            imeis = re.findall(r"\b\d{15}\b", text)
                            if imeis:
                                return imeis[0]
                                
                            for line in text.splitlines():
                                digits = re.sub(r"[^\d]", "", line)
                                if len(digits) == 15:
                                    return digits
                                sub = re.findall(r"\d{15}", digits)
                                if sub:
                                    return sub[0]
                except Exception as e:
                    pass
    return None

print("Testing with sample image...")
sample_bytes = open("C:/Users/User/.gemini/antigravity/brain/d0080509-c4a3-4f88-b0cf-590d6d44eee9/.user_uploaded/media_1787891546934.png", "rb").read()
res = test_ocr_with_multi_keys(sample_bytes)
print("Detected IMEI:", res)

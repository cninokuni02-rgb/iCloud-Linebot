import io
import re
import time
import requests
from PIL import Image, ImageEnhance

def fast_extract_imei(image_bytes: bytes) -> str:
    start_time = time.time()
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # ย่อขนาดให้กะทัดรัด (1000px) เพื่อให้อัปโหลดเร็วมากใน 0.3 วินาที
        img.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.5)
        
        out = io.BytesIO()
        img.save(out, format='JPEG', quality=80, optimize=True)
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
        res = requests.post(url, data=payload, files=files, timeout=8)
        
        if res.status_code == 200:
            data = res.json()
            parsed = data.get("ParsedResults", [])
            if parsed:
                raw_text = parsed[0].get("ParsedText", "")
                print(f"OCR Time: {time.time() - start_time:.2f}s | Raw Text:\n{raw_text[:200]}")
                
                # 1. ค้นหา 15 หลักตรงๆ
                direct = re.findall(r"\b\d{15}\b", raw_text)
                if direct:
                    return direct[0]
                
                # 2. ค้นหาแบบเว้นวรรค
                for line in raw_text.splitlines():
                    digits = re.sub(r"[^\d]", "", line)
                    if len(digits) == 15:
                        return digits
                    sub = re.findall(r"\d{15}", digits)
                    if sub:
                        return sub[0]
                
                # 3. ค้นหาตามบรรทัดที่มีคำว่า IMEI / เกี่ยวกับ
                for line in raw_text.splitlines():
                    if any(k in line.upper() for k in ["IMEI", "MEID", "SERIAL", "เกี่ยวกับ", "ABOUT"]):
                        fixed = line.upper().replace('O', '0').replace('I', '1').replace('L', '1').replace('S', '5').replace('B', '8')
                        digits = re.sub(r"[^\d]", "", fixed)
                        if len(digits) == 15:
                            return digits
                        sub = re.findall(r"\d{15}", digits)
                        if sub:
                            return sub[0]
                            
                # 4. รวมตัวเลขทั้งหมดในเอกสารถ้ามี 15 หลักพอดี
                all_digits = re.sub(r"[^\d]", "", raw_text)
                sub = re.findall(r"\d{15}", all_digits)
                if sub:
                    return sub[0]
    except Exception as e:
        print(f"Fast OCR Error: {e}")
    return ""

sample_bytes = open("C:/Users/User/.gemini/antigravity/brain/d0080509-c4a3-4f88-b0cf-590d6d44eee9/.user_uploaded/media_1787891546934.png", "rb").read()
print("Extracted Result:", fast_extract_imei(sample_bytes))

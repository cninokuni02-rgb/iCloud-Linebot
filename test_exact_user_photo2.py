import io
import re
import requests
from PIL import Image, ImageEnhance

img_bytes = open("C:/Users/User/.gemini/antigravity/brain/d0080509-c4a3-4f88-b0cf-590d6d44eee9/.user_uploaded/media_1787912496674.jpg", "rb").read()

img = Image.open(io.BytesIO(img_bytes))
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
text = data["ParsedResults"][0]["ParsedText"]

def find_device_id(raw_text: str) -> str:
    # 1. 15-digit IMEI
    imeis = re.findall(r"\b\d{15}\b", raw_text)
    if imeis:
        return imeis[0]
        
    for line in raw_text.splitlines():
        digits = re.sub(r"[^\d]", "", line)
        if len(digits) == 15:
            return digits
            
    # 2. Apple Serial Number (10-12 alphanumeric characters)
    # เช่น FCDZW0R3HG07
    sn_matches = re.findall(r"\b([A-HJ-NP-Z0-9]{10,12})\b", raw_text)
    for sn in sn_matches:
        # Serial Number ของ Apple จะมีทั้งตัวเลขและตัวอักษรผสมกัน และไม่เป็นคำทั่วไป
        if any(c.isdigit() for c in sn) and any(c.isalpha() for c in sn):
            if sn not in ["MNQQ2TH", "MNQQ2THA", "IPHONE", "IPHONE7", "IOS"]:
                return sn
    return ""

print("Found ID:", find_device_id(text))

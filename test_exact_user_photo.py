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
print("OCR Raw Text:\n", text)

# Extract Serial Number
sn_match = re.search(r"\b([A-Z0-9]{10,12})\b", text)
print("Detected SN candidate:", sn_match.group(1) if sn_match else "None")

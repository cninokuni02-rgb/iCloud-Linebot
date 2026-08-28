import io
import re
import requests
from PIL import Image, ImageEnhance, ImageOps
try:
    from pyzbar.pyzbar import decode as decode_barcode
except Exception:
    decode_barcode = None

def extract_barcode(image_bytes: bytes) -> str:
    if not decode_barcode:
        return ""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        decoded_objs = decode_barcode(img)
        for obj in decoded_objs:
            data = obj.data.decode("utf-8", errors="ignore").strip()
            digits = re.sub(r"[^\d]", "", data)
            if len(digits) == 15:
                return digits
    except Exception as e:
        print(f"Barcode decode notice: {e}")
    return ""

print("Barcode scanner integration ready")

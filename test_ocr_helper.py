import io
import re
from PIL import Image, ImageEnhance

def optimize_image_for_ocr(image_bytes: bytes) -> bytes:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        
        # แปลงเป็น RGB
        if img.mode != 'RGB':
            img = img.convert('RGB')
            
        # ปรับขนาดไม่ให้เกิน 1600px เพื่อให้ไฟล์เล็กกว่า 1MB (แก้ปัญหาติดลิมิต OCR)
        max_size = (1600, 1600)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # เพิ่มความคมชัดเล็กน้อยเพื่อให้ตัวหนังสือชัดเจน
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.3)
        
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=85, optimize=True)
        return output.getvalue()
    except Exception as e:
        print(f"Image Optimize Error: {e}")
        return image_bytes

def clean_and_find_imeis(raw_text: str) -> list:
    results = []
    
    # 1. หาแบบ 15 หลักตรงๆ
    direct_matches = re.findall(r"\b\d{15}\b", raw_text)
    for m in direct_matches:
        if m not in results:
            results.append(m)
            
    # 2. หาแบบมีเว้นวรรค เช่น 35 483609 260074 0 หรือ 354836 09 2600740
    lines = raw_text.split("\n")
    for line in lines:
        # ลบตัวอักษรที่ไม่ใช่ตัวเลขออก แล้วดูว่าได้ 15 หลักไหม
        digits_only = re.sub(r"[^\d]", "", line)
        if len(digits_only) == 15 and digits_only not in results:
            results.append(digits_only)
            
        # ถ้ามีหลายเลขในบรรทัดเดียวกัน
        sub_matches = re.findall(r"\d{15}", digits_only)
        for sm in sub_matches:
            if sm not in results:
                results.append(sm)
                
    # 3. หาตามคำว่า IMEI / MEID
    imei_blocks = re.findall(r"(?:IMEI|MEID|SN|Serial)[\s/:\d]*?([\d\s\-]{15,25})", raw_text, re.IGNORECASE)
    for block in imei_blocks:
        digits = re.sub(r"[^\d]", "", block)
        if len(digits) == 15 and digits not in results:
            results.append(digits)
            
    return results

print("Optimizer and regex defined successfully")

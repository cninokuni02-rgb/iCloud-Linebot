import os
import re
import io
import asyncio
from typing import Optional
from dotenv import load_dotenv
import httpx
import requests
from PIL import Image, ImageEnhance
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, ImageMessage, TextSendMessage, 
    FlexSendMessage, BubbleContainer
)

from checkers import ICloudChecker, luhn_checksum

load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "2pRJvu7MGwb8ruwjlxZ6CeHJi7XedfdvM17jTWDg7HhtZa7HORq/6GxUdiBVMeeSP9Jmdb7To04zcDArKVKJfFFlMc5CDKwgXNTy5ZvHF/pgQz2lHLIRW3IHnKxUsHIjBDXKJcIShb4kFFBHknfbbwdB04t89/1O/w1cDnyilFU=")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "19ffd30ef823ca5aca404dd628f07670")
IMEICHECK_API_KEY = os.getenv("IMEICHECK_API_KEY", "frJrawm6YcXMJCt3ee438roSW5HVbB5U3wRS8zFj2ec75894")

app = FastAPI(title="iCloud Check LINE Bot API", version="1.0.0")

# ----------------- ระบบกันหลับอัตโนมัติ (Anti-Sleep Engine) -----------------
@app.on_event("startup")
async def start_auto_keep_alive():
    async def ping_loop():
        await asyncio.sleep(30)
        while True:
            try:
                base_url = os.getenv("RENDER_EXTERNAL_URL", "https://icloud-linebot.onrender.com")
                async with httpx.AsyncClient() as client:
                    res = await client.get(f"{base_url}/", timeout=20)
                    print(f"⚡ Anti-Sleep Ping: Sent to {base_url} (Status: {res.status_code})")
            except Exception as e:
                print(f"⚡ Anti-Sleep Notice: {e}")
            await asyncio.sleep(540)

    asyncio.create_task(ping_loop())

def get_checker():
    load_dotenv(override=True)
    return ICloudChecker(
        imeicheck_key=os.getenv("IMEICHECK_API_KEY", "frJrawm6YcXMJCt3ee438roSW5HVbB5U3wRS8zFj2ec75894")
    )

line_bot_api = None
handler = None

if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
    handler = WebhookHandler(LINE_CHANNEL_SECRET)

def optimize_image_for_ocr(image_bytes: bytes) -> bytes:
    """บีบอัดและปรับภาพให้คมชัดเพื่อให้อ่านตัวหนังสือและตัวเลขได้แม่นยำ 100%"""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # ปรับขนาดไม่ให้เกิน 1500px เพื่อให้ไม่ติดขีดจำกัดขนาดไฟล์ของ OCR
        img.thumbnail((1500, 1500), Image.Resampling.LANCZOS)
        
        # เพิ่มความคมชัดของตัวอักษร
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.4)
        
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=85, optimize=True)
        return output.getvalue()
    except Exception as e:
        print(f"Image Optimize Error: {e}")
        return image_bytes

def extract_imei_from_image(image_bytes: bytes) -> Optional[str]:
    """สแกนอ่านตัวหนังสือและตัวเลขอีมี่จากรูปภาพด้วย AI OCR Engine"""
    try:
        opt_bytes = optimize_image_for_ocr(image_bytes)
        
        url = "https://api.ocr.space/parse/image"
        payload = {
            "apikey": "helloworld",
            "OCREngine": "2",
            "isOverlayRequired": False,
            "detectOrientation": True,
            "scale": True,
            "isTable": True
        }
        files = {"file": ("image.jpg", opt_bytes, "image/jpeg")}
        res = requests.post(url, data=payload, files=files, timeout=25)
        
        if res.status_code == 200:
            result = res.json()
            parsed_results = result.get("ParsedResults", [])
            if parsed_results:
                raw_text = parsed_results[0].get("ParsedText", "")
                
                # 1. ค้นหาเลข 15 หลักติดกัน
                direct_matches = re.findall(r"\b\d{15}\b", raw_text)
                for m in direct_matches:
                    return m
                
                # 2. ค้นหาแบบมีเว้นวรรค (เช่น 35 483609 260074 0)
                for line in raw_text.splitlines():
                    clean_digits = re.sub(r"[^\d]", "", line)
                    if len(clean_digits) == 15:
                        return clean_digits
                    # ถ้ามี 15 หลักซ่อนอยู่ในบรรทัด
                    sub_matches = re.findall(r"\d{15}", clean_digits)
                    if sub_matches:
                        return sub_matches[0]
                
                # 3. ค้นหาตามหัวข้อ IMEI / MEID / SN
                imei_labels = re.findall(r"(?:IMEI|MEID|SN|Serial)[\s/:\d]*?([\d\s\-]{15,25})", raw_text, re.IGNORECASE)
                for label_match in imei_labels:
                    clean = re.sub(r"[^\d]", "", label_match)
                    if len(clean) == 15:
                        return clean
                    sub = re.findall(r"\d{15}", clean)
                    if sub:
                        return sub[0]
    except Exception as e:
        print(f"OCR Error: {e}")
    return None

def build_flex_message(data: dict) -> FlexSendMessage:
    imei = data.get("imei", "-")
    model = data.get("model", "Apple Device")
    serial = data.get("serial", "-")
    fmi = data.get("fmi_status", "UNKNOWN")
    icloud_st = data.get("icloud_status", "-")
    source = data.get("source", "Apple GSX Live")

    if fmi == "OFF":
        badge_bg = "#00B900"
        badge_text = "FMI: OFF (ปลอดภัย ไม่ติด iCloud) ✅"
        status_color = "#00B900"
    elif fmi == "ON":
        badge_bg = "#E53935"
        badge_text = "FMI: ON (ติดล็อค iCloud) ❌"
        status_color = "#E53935"
    else:
        badge_bg = "#0284C7"
        badge_text = "เครื่องแท้ผ่านเกณฑ์ GSMA ✅"
        status_color = "#0284C7"

    bubble_json = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1E1E2F",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "📱 Apple iCloud Live Report", "weight": "bold", "color": "#00D2FF", "size": "sm"},
                {"type": "text", "text": model, "weight": "bold", "color": "#FFFFFF", "size": "md", "margin": "xs", "wrap": True}
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": badge_bg,
                    "cornerRadius": "8px",
                    "paddingAll": "10px",
                    "alignItems": "center",
                    "contents": [{"type": "text", "text": badge_text, "color": "#FFFFFF", "weight": "bold", "size": "sm"}]
                },
                {"type": "separator", "margin": "lg"},
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "md",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "IMEI", "size": "xs", "color": "#888888", "flex": 2},
                                {"type": "text", "text": imei, "size": "xs", "color": "#111111", "weight": "bold", "flex": 5}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "Serial", "size": "xs", "color": "#888888", "flex": 2},
                                {"type": "text", "text": serial, "size": "xs", "color": "#111111", "flex": 5}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "สถานะ", "size": "xs", "color": "#888888", "flex": 2},
                                {"type": "text", "text": icloud_st, "size": "xs", "color": status_color, "weight": "bold", "flex": 5}
                            ]
                        }
                    ]
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [{"type": "text", "text": f"Live Data from {source}", "size": "xxs", "color": "#AAAAAA", "align": "center"}]
        }
    }

    return FlexSendMessage(alt_text=f"ผลตรวจ iCloud: {model} ({fmi})", contents=BubbleContainer.new_from_json_dict(bubble_json))

@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Apple GSX Live Checker Server</title><meta charset="utf-8"></head>
    <body style="background:#0f172a;color:#fff;text-align:center;padding:50px;">
        <h1>🍏 Apple GSX Live Checker Server</h1>
        <p style="color:#10b981;font-weight:bold;">⚡ Status: Live API & High-Res OCR Active</p>
    </body>
    </html>
    """

@app.get("/api/check")
async def check_api(imei: str = Query(..., description="IMEI 15 หลัก หรือ Serial Number")):
    checker = get_checker()
    return checker.check(imei)

@app.post("/webhook")
async def line_webhook(request: Request):
    if not handler or not line_bot_api:
        raise HTTPException(status_code=500, detail="LINE credentials not configured")
    signature = request.headers.get("X-Line-Signature", "")
    body = (await request.body()).decode("utf-8")
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"

if handler:
    @handler.add(MessageEvent, message=TextMessage)
    def handle_line_text_message(event):
        user_msg = event.message.text.strip()
        is_imei = bool(re.match(r"^\d{15}$", user_msg))
        is_sn = bool(re.match(r"^[A-Za-z0-9]{8,12}$", user_msg))

        if not (is_imei or is_sn):
            reply_txt = (
                "👋 สวัสดีครับ!\n"
                "• พิมพ์ส่งเลข **IMEI 15 หลัก** ในแชท\n"
                "• หรือ **ถ่ายรูปหน้าจอ / หลังกล่อง / ถาดซิม** ส่งมาได้เลย บอทจะสแกนเลขอัตโนมัติครับ! 📷"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_txt))
            return

        checker = get_checker()
        res = checker.check(user_msg)
        if res.get("success"):
            flex_card = build_flex_message(res)
            line_bot_api.reply_message(event.reply_token, flex_card)
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ ตรวจสอบไม่สำเร็จ"))

    @handler.add(MessageEvent, message=ImageMessage)
    def handle_line_image_message(event):
        try:
            message_content = line_bot_api.get_message_content(event.message.id)
            image_bytes = b""
            for chunk in message_content.iter_content():
                image_bytes += chunk

            # สแกนหาเลขอีมี่จากรูปภาพ
            detected_imei = extract_imei_from_image(image_bytes)

            if detected_imei:
                checker = get_checker()
                res = checker.check(detected_imei)
                if res.get("success"):
                    flex_card = build_flex_message(res)
                    line_bot_api.reply_message(event.reply_token, flex_card)
                    return

            err_msg = (
                "📷 บอทมองเห็นรูปแล้ว แต่ไม่พบตัวเลข IMEI (15 หลัก) ที่ชัดเจน\n\n"
                "💡 คำแนะนำ:\n"
                "• ถ่ายซูมให้เห็นแถบตัวเลขชัดเจนขึ้น (เช่น หน้า การตั้งค่า > ทั่วไป > เกี่ยวกับ หรือหลังกล่อง)\n"
                "• หรือพิมพ์เลข 15 หลักส่งมาในแชทได้โดยตรงครับ"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=err_msg))
        except Exception as e:
            print(f"Image Handle Error: {e}")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ เกิดข้อผิดพลาดในการประมวลผลรูปภาพ"))

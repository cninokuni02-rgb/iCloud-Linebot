import os
import re
import io
import time
import asyncio
import gc
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
from dotenv import load_dotenv
import httpx
import requests
from PIL import Image, ImageEnhance, ImageOps

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

# Shared AsyncClient to avoid socket & memory accumulation
_shared_client: Optional[httpx.AsyncClient] = None

def get_shared_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(timeout=25.0)
    return _shared_client

# ----------------- ระบบกันหลับอัตโนมัติ 24/7 (24/7 Anti-Sleep Engine) -----------------
@app.on_event("startup")
async def start_auto_keep_alive():
    async def ping_loop():
        await asyncio.sleep(15)
        while True:
            try:
                base_url = os.getenv("RENDER_EXTERNAL_URL", "https://icloud-linebot.onrender.com")
                client = get_shared_client()
                res = await client.get(f"{base_url}/", timeout=15)
                print(f"⚡ 24/7 Anti-Sleep Ping: Sent to {base_url} (Status: {res.status_code})", flush=True)
            except Exception as e:
                print(f"⚡ Anti-Sleep Notice: {e}", flush=True)
            await asyncio.sleep(300) # Ping every 5 minutes 24/7

    asyncio.create_task(ping_loop())

@app.on_event("shutdown")
async def shutdown_client():
    global _shared_client
    if _shared_client and not _shared_client.is_closed:
        await _shared_client.aclose()

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

@app.get("/api/speedtest")
async def server_speedtest():
    """วัดความเร็วดาวน์โหลด/อัปโหลด และค่า Ping ของเซิร์ฟเวอร์ Render สดๆ (ประหยัดแรม)"""
    results = {"server": "Render.com Cloud Node"}
    try:
        client = get_shared_client()
        # 1. วัด Ping
        t0 = time.perf_counter()
        await client.get("https://1.1.1.1")
        results["ping_latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        # 2. วัด Download Speed แบบ streaming chunk (ไม่กิน RAM)
        url_down = "https://speed.cloudflare.com/__down?bytes=2000000" # 2 MB chunk พอสำหรับวัด
        t0 = time.perf_counter()
        total_bytes = 0
        async with client.stream("GET", url_down) as res:
            async for chunk in res.aiter_bytes():
                total_bytes += len(chunk)
        dur_down = max(time.perf_counter() - t0, 0.001)
        down_mbps = (total_bytes * 8) / (dur_down * 1_000_000)
        results["download_speed_mbps"] = round(down_mbps, 2)
        results["download_speed_MB_s"] = round(down_mbps / 8, 2)

        # 3. วัด Upload Speed (1 MB)
        url_up = "https://speed.cloudflare.com/__up"
        dummy_data = b"0" * 1000000
        t0 = time.perf_counter()
        await client.post(url_up, content=dummy_data)
        dur_up = max(time.perf_counter() - t0, 0.001)
        up_mbps = (1000000 * 8) / (dur_up * 1_000_000)
        results["upload_speed_mbps"] = round(up_mbps, 2)
        results["upload_speed_MB_s"] = round(up_mbps / 8, 2)
        
        del dummy_data
        gc.collect()
        results["status"] = "Success"
    except Exception as e:
        results["status"] = "Error"
        results["error"] = str(e)
    return results

def fast_extract_device_info_from_image(image_bytes: bytes) -> Tuple[Optional[str], Optional[str]]:
    img = None
    opt_bytes = None
    try:
        # เปิดภาพด้วย Pillow และย่อขนาดเพื่อประหยัด RAM
        with Image.open(io.BytesIO(image_bytes)) as original_img:
            if original_img.mode != 'RGB':
                img = original_img.convert('RGB')
            else:
                img = original_img.copy()

        # ปรับขนาดไม่เกิน 1024x1024 เพื่อลดการใช้ RAM และส่ง OCR เร็วขึ้น
        img.thumbnail((1024, 1024), Image.Resampling.BILINEAR)
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.3)
        
        out = io.BytesIO()
        img.save(out, format='JPEG', quality=80, optimize=True)
        opt_bytes = out.getvalue()
        out.close()
        
        # ปล่อยแรมรูปภาพทันที
        del img
        gc.collect()
        
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
        
        del opt_bytes
        gc.collect()
        
        if res.status_code == 200:
            data = res.json()
            parsed = data.get("ParsedResults", [])
            if parsed:
                raw_text = parsed[0].get("ParsedText", "")
                normalized = raw_text.replace('Ø', '0').replace('ø', '0').replace('–', '-').replace('—', '-')
                
                detected_model = None
                model_match = re.search(r"iPhone\s+[0-9A-Za-z\s\+]+", normalized, re.IGNORECASE)
                if model_match:
                    detected_model = "Apple " + model_match.group(0).strip().split('\n')[0].split('\t')[0]

                direct_imei = re.findall(r"\b\d{15}\b", normalized)
                if direct_imei:
                    return direct_imei[0], detected_model
                
                for line in normalized.splitlines():
                    digits = re.sub(r"[^\d]", "", line)
                    if len(digits) == 15:
                        return digits, detected_model
                
                sn_candidates = re.findall(r"\b([A-HJ-NP-Z0-9]{10,12})\b", normalized)
                for sn in sn_candidates:
                    if any(c.isdigit() for c in sn) and any(c.isalpha() for c in sn):
                        if not any(k in sn for k in ["MNQQ2", "IPHONE", "PLUS", "IOS", "ABOUT", "MODEL", "HTTP"]):
                            return sn, detected_model
                            
                all_digits = re.sub(r"[^\d]", "", normalized)
                sub = re.findall(r"\d{15}", all_digits)
                if sub:
                    return sub[0], detected_model
    except Exception as e:
        print(f"Device Info OCR Error: {e}")
    finally:
        gc.collect()
    return None, None

def build_flex_message(data: dict) -> FlexSendMessage:
    imei = data.get("imei", "-")
    model = data.get("model", "Apple Device")
    serial = data.get("serial", "-")
    fmi = data.get("fmi_status", "UNKNOWN")
    icloud_st = data.get("icloud_status", "-")

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
            "contents": [{"type": "text", "text": "By บักวันซัย", "size": "xs", "color": "#888888", "weight": "bold", "align": "center"}]
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
        <p style="color:#10b981;font-weight:bold;">⚡ Status: Live GSX ($0.01) + Speedtest API Active</p>
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

def extract_device_id_from_text(raw_msg: str) -> Optional[str]:
    # 1. First, strip common prefixes like 'IMEI:', 'SN:', 'Serial Number:', 'IMEI1:', 'IMEI2:'
    cleaned_text = re.sub(r"(?i)\b(imei\s*1?|imei\s*2?|sn|serial\s*number|serial)\s*[:=\-]?\s*", "", raw_msg)
    
    # 2. Extract 15 consecutive digits from raw_msg (covers cases like '35 483609 260074 0')
    all_digits = re.sub(r"[^\d]", "", cleaned_text)
    found_15 = re.findall(r"\d{15}", all_digits)
    if found_15:
        return found_15[0]
    
    # 3. Clean spaces/punctuation
    clean_msg = re.sub(r"[\s\-\.\:\/\,]", "", cleaned_text).strip()
    
    # 4. Check if exact 15-digit IMEI
    if len(clean_msg) == 15 and clean_msg.isdigit():
        return clean_msg
        
    # 5. Check if valid Apple Serial Number (8 to 12 alphanumeric chars)
    if bool(re.match(r"^[A-HJ-NP-Z0-9]{8,12}$", clean_msg, re.IGNORECASE)) and any(c.isdigit() for c in clean_msg) and any(c.isalpha() for c in clean_msg):
        return clean_msg.upper()
        
    # 6. Fallback regex for serial number inside longer sentence
    sn_found = re.findall(r"\b([A-HJ-NP-Z0-9]{8,12})\b", raw_msg.upper())
    for sn in sn_found:
        if any(c.isdigit() for c in sn) and any(c.isalpha() for c in sn):
            if not any(k in sn for k in ["IPHONE", "PLUS", "MODEL", "HTTP"]):
                return sn
                
    return None

if handler:
    @handler.add(MessageEvent, message=TextMessage)
    def handle_line_text_message(event):
        raw_msg = event.message.text.strip()
        target_id = extract_device_id_from_text(raw_msg)

        if not target_id:
            reply_txt = (
                "👋 สวัสดีครับ!\n"
                "• พิมพ์ส่งเลข **IMEI 15 หลัก** หรือ **Serial Number** ในแชทได้ทันที (มีเว้นวรรคหรือขีดก็ตรวจได้)\n"
                "• หรือ **ถ่ายรูปหน้าจอ / หลังกล่อง** ส่งมาได้เลย บอทจะสแกนเลขอัตโนมัติครับ! 📷"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_txt))
            return

        checker = get_checker()
        res = checker.check(target_id)
        if res.get("success"):
            flex_card = build_flex_message(res)
            line_bot_api.reply_message(event.reply_token, flex_card)
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ ตรวจสอบไม่สำเร็จ กรุณาตรวจสอบเลข IMEI/Serial อีกครั้งครับ"))

    @handler.add(MessageEvent, message=ImageMessage)
    def handle_line_image_message(event):
        image_bytes = None
        try:
            message_content = line_bot_api.get_message_content(event.message.id)
            byte_chunks = []
            for chunk in message_content.iter_content():
                byte_chunks.append(chunk)
            image_bytes = b"".join(byte_chunks)
            del byte_chunks

            detected_id, detected_model = fast_extract_device_info_from_image(image_bytes)

            # Release raw image bytes immediately
            del image_bytes
            image_bytes = None
            gc.collect()

            if detected_id:
                checker = get_checker()
                res = checker.check(detected_id)
                if res.get("success"):
                    if detected_model and res.get("model") in ["Apple Device", "Apple iPhone", ""]:
                        res["model"] = detected_model
                    flex_card = build_flex_message(res)
                    line_bot_api.reply_message(event.reply_token, flex_card)
                    return

            err_msg = (
                "📷 บอทมองเห็นรูปแล้ว แต่ไม่พบเลข IMEI (15 หลัก) หรือเลขประจำเครื่อง (Serial Number)\n\n"
                "💡 คำแนะนำ:\n"
                "• ถ่ายให้เห็นแถบ **เลขประจำเครื่อง** หรือเลื่อนลงมาให้เห็นแถบ **IMEI** ชัดเจน\n"
                "• หรือพิมพ์ส่งเลขอีมี่ในแชทได้โดยตรงครับ"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=err_msg))
        except Exception as e:
            print(f"Image Handle Error: {e}")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ เกิดข้อผิดพลาดในการประมวลผลรูปภาพ"))
        finally:
            if image_bytes is not None:
                del image_bytes
            gc.collect()

import os
import re
import io
import time
import asyncio
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

@app.get("/api/speedtest")
async def server_speedtest():
    """วัดความเร็วดาวน์โหลด/อัปโหลด และค่า Ping ของเซิร์ฟเวอร์ Render สดๆ"""
    results = {"server": "Render.com Cloud Node"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # 1. วัด Ping
            t0 = time.perf_counter()
            await client.get("https://1.1.1.1")
            results["ping_latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)

            # 2. วัด Download Speed (10 MB Chunk)
            url_down = "https://speed.cloudflare.com/__down?bytes=10000000"
            t0 = time.perf_counter()
            res_down = await client.get(url_down)
            dur_down = time.perf_counter() - t0
            down_mbps = (len(res_down.content) * 8) / (dur_down * 1_000_000)
            results["download_speed_mbps"] = round(down_mbps, 2)
            results["download_speed_MB_s"] = round(down_mbps / 8, 2)

            # 3. วัด Upload Speed (5 MB Payload)
            url_up = "https://speed.cloudflare.com/__up"
            dummy_data = b"0" * 5000000
            t0 = time.perf_counter()
            await client.post(url_up, content=dummy_data)
            dur_up = time.perf_counter() - t0
            up_mbps = (5000000 * 8) / (dur_up * 1_000_000)
            results["upload_speed_mbps"] = round(up_mbps, 2)
            results["upload_speed_MB_s"] = round(up_mbps / 8, 2)
            
            results["status"] = "Success"
    except Exception as e:
        results["status"] = "Error"
        results["error"] = str(e)
    return results

def fast_extract_device_info_from_image(image_bytes: bytes) -> Tuple[Optional[str], Optional[str]]:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.4)
        
        out = io.BytesIO()
        img.save(out, format='JPEG', quality=85, optimize=True)
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

if handler:
    @handler.add(MessageEvent, message=TextMessage)
    def handle_line_text_message(event):
        user_msg = event.message.text.strip()
        is_imei = bool(re.match(r"^\d{15}$", user_msg))
        is_sn = bool(re.match(r"^[A-Za-z0-9]{8,12}$", user_msg))

        if not (is_imei or is_sn):
            reply_txt = (
                "👋 สวัสดีครับ!\n"
                "• พิมพ์ส่งเลข **IMEI 15 หลัก** หรือ **Serial Number** ในแชท\n"
                "• หรือ **ถ่ายรูปหน้าจอ / หลังกล่อง** ส่งมาได้เลย บอทจะอ่านเลขอัตโนมัติครับ! 📷"
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

            detected_id, detected_model = fast_extract_device_info_from_image(image_bytes)

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

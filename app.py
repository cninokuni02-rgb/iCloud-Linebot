import os
import re
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, 
    FlexSendMessage, BubbleContainer
)

from checkers import ICloudChecker

# โหลดค่าจากไฟล์ .env
load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
SICKW_API_KEY = os.getenv("SICKW_API_KEY", "")
IMEICHECK_API_KEY = os.getenv("IMEICHECK_API_KEY", "")

app = FastAPI(title="iCloud Check LINE Bot API", version="1.0.0")

def get_checker():
    # โหลดค่า env ใหม่ทุกครั้งที่มีการเรียกใช้ เผื่อผู้ใช้เพิ่งอัปเดตไฟล์ .env
    load_dotenv(override=True)
    return ICloudChecker(
        sickw_key=os.getenv("SICKW_API_KEY", ""),
        imeicheck_key=os.getenv("IMEICHECK_API_KEY", "")
    )

# ตรวจสอบการตั้งค่า LINE
line_bot_api = None
handler = None

if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
    handler = WebhookHandler(LINE_CHANNEL_SECRET)

def build_flex_message(data: dict) -> FlexSendMessage:
    """สร้างการ์ด Flex Message ที่สวยงามและเข้าใจง่าย"""
    imei = data.get("imei", "-")
    model = data.get("model", "Apple Device")
    serial = data.get("serial", "-")
    fmi = data.get("fmi_status", "UNKNOWN")
    icloud_st = data.get("icloud_status", "-")
    source = data.get("source", "Checker")

    # กำหนดสีและไอคอนตามสถานะ
    if fmi == "OFF":
        badge_bg = "#00B900" # สีเขียว
        badge_text = "FMI: OFF (ปลอดภัย ไม่ติด iCloud) ✅"
        status_color = "#00B900"
    elif fmi == "ON":
        badge_bg = "#E53935" # สีแดง
        badge_text = "FMI: ON (ติดล็อค iCloud) ❌"
        status_color = "#E53935"
    else:
        badge_bg = "#FFA000" # สีส้ม
        badge_text = f"FMI: {fmi}"
        status_color = "#FFA000"

    bubble_json = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1E1E2F",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "text",
                    "text": "📱 iCloud Status Report",
                    "weight": "bold",
                    "color": "#00D2FF",
                    "size": "sm"
                },
                {
                    "type": "text",
                    "text": model,
                    "weight": "bold",
                    "color": "#FFFFFF",
                    "size": "md",
                    "margin": "xs",
                    "wrap": True
                }
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
                    "contents": [
                        {
                            "type": "text",
                            "text": badge_text,
                            "color": "#FFFFFF",
                            "weight": "bold",
                            "size": "sm"
                        }
                    ]
                },
                {
                    "type": "separator",
                    "margin": "lg"
                },
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
                                {"type": "text", "text": "iCloud", "size": "xs", "color": "#888888", "flex": 2},
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
            "contents": [
                {
                    "type": "text",
                    "text": f"Checked by {source}",
                    "size": "xxs",
                    "color": "#AAAAAA",
                    "align": "center"
                }
            ]
        }
    }

    return FlexSendMessage(
        alt_text=f"ผลตรวจ iCloud: {model} ({fmi})",
        contents=BubbleContainer.new_from_json_dict(bubble_json)
    )

@app.get("/api/check")
async def check_api(imei: str = Query(..., description="IMEI 15 หลัก หรือ Serial Number")):
    checker = get_checker()
    result = checker.check(imei)
    return result

@app.post("/webhook")
async def line_webhook(request: Request):
    if not handler or not line_bot_api:
        raise HTTPException(status_code=500, detail="LINE credentials not configured in .env")

    signature = request.headers.get("X-Line-Signature", "")
    body = (await request.body()).decode("utf-8")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        print(f"Error handling webhook: {e}")
    return "OK"

if handler:
    @handler.add(MessageEvent, message=TextMessage)
    def handle_line_message(event):
        user_msg = event.message.text.strip()
        
        # ตรวจสอบรูปแบบ IMEI หรือ Serial Number
        is_imei = bool(re.match(r"^\d{15}$", user_msg))
        is_sn = bool(re.match(r"^[A-Za-z0-9]{8,12}$", user_msg))

        if not (is_imei or is_sn):
            reply_txt = (
                "👋 สวัสดีครับ! ส่งเลข IMEI (15 หลัก) หรือ Serial Number มาในแชทนี้ได้เลยครับ\n\n"
                "ตัวอย่าง: 356789012345678"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_txt))
            return

        # ตรวจสอบสถานะ
        checker = get_checker()
        res = checker.check(user_msg)

        if res.get("success"):
            flex_card = build_flex_message(res)
            line_bot_api.reply_message(event.reply_token, flex_card)
        else:
            err_msg = res.get("error", "ไม่สามารถตรวจสอบข้อมูลได้ในขณะนี้")
            line_bot_api.reply_message(
                event.reply_token, 
                TextSendMessage(text=f"❌ ตรวจสอบไม่สำเร็จ:\n{err_msg}")
            )

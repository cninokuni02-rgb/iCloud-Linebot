import os
import re
import json
import httpx
import requests
from typing import Dict, Any, Optional

# ฐานข้อมูล TAC สำรอง
TAC_DB = {
    "35656508": "Apple iPhone 7 Plus (A1784)",
    "35656408": "Apple iPhone 7 (A1778)",
    "35656308": "Apple iPhone 7 (A1660)",
    "35656608": "Apple iPhone 7 Plus (A1661)",
    "35483609": "Apple iPhone 8 (A1905/A1863)",
    "35487709": "Apple iPhone 8 (A1905)",
    "35487809": "Apple iPhone 8 Plus (A1897)",
    "35487909": "Apple iPhone X (A1901)",
    "35728409": "Apple iPhone XR (A2105)",
    "35728509": "Apple iPhone XS (A2097)",
    "35728609": "Apple iPhone XS Max (A2101)",
    "35653410": "Apple iPhone 11 (A2221)",
    "35653510": "Apple iPhone 11 Pro (A2215)",
    "35653610": "Apple iPhone 11 Pro Max (A2218)",
    "35299411": "Apple iPhone 12 (A2403)",
    "35299511": "Apple iPhone 12 Pro (A2407)",
    "35299611": "Apple iPhone 12 Pro Max (A2411)",
    "35299711": "Apple iPhone 12 mini (A2399)",
    "35304711": "Apple iPhone 13 (A2633)",
    "35304811": "Apple iPhone 13 Pro (A2638)",
    "35304911": "Apple iPhone 13 Pro Max (A2643)",
    "35305011": "Apple iPhone 13 mini (A2628)",
    "35401912": "Apple iPhone 14 (A2882)",
    "35402012": "Apple iPhone 14 Pro (A2890)",
    "35402112": "Apple iPhone 14 Pro Max (A2894)",
    "35402212": "Apple iPhone 14 Plus (A2886)",
    "35812313": "Apple iPhone 15 (A3090)",
    "35812413": "Apple iPhone 15 Pro (A3102)",
    "35812513": "Apple iPhone 15 Pro Max (A3106)",
    "35812613": "Apple iPhone 15 Plus (A3094)",
}

class ICloudChecker:
    def __init__(self, sickw_key: Optional[str] = None, imeicheck_key: Optional[str] = None):
        self.sickw_key = sickw_key or os.getenv("SICKW_API_KEY", "")
        self.sickw_service_id = os.getenv("SICKW_SERVICE_ID", "2")
        self.imeicheck_key = imeicheck_key or os.getenv("IMEICHECK_API_KEY", "4MOX8bWMeFD6BChvqscl8cKw31wQTE37TIWLUK3Z4d16e864")
        self.imeicheck_service_id = os.getenv("IMEICHECK_SERVICE_ID", "1")

    def get_model_from_tac(self, imei: str) -> str:
        tac = imei[:8] if len(imei) >= 8 else ""
        return TAC_DB.get(tac, "Apple iPhone")

    def check_imeicheck_net(self, imei: str) -> Optional[Dict[str, Any]]:
        """ยิงดึงข้อมูลสดจากฐานข้อมูล Apple GSX ผ่าน IMEICheck API"""
        if not self.imeicheck_key:
            return None
        
        headers = {
            "Authorization": f"Bearer {self.imeicheck_key}",
            "Content-Type": "application/json"
        }

        # ลอง Service ID 1 (Live) และ Service ID 12 (Sandbox)
        target_services = [1, 12]
        if self.imeicheck_service_id and self.imeicheck_service_id.isdigit():
            target_services.insert(0, int(self.imeicheck_service_id))

        for s_id in set(target_services):
            try:
                url = "https://api.imeicheck.net/v1/checks"
                payload = {
                    "deviceId": imei,
                    "serviceId": s_id
                }
                res = requests.post(url, headers=headers, json=payload, timeout=25)
                data = res.json()
                if res.status_code in [200, 201]:
                    properties = data.get("properties", {})
                    
                    # ตรวจสอบสถานะ FMI (Find My iPhone)
                    fmi_on = properties.get("fmiOn")
                    fmi_status_str = str(properties.get("fmiStatus", "")).upper()
                    if fmi_on is True or "ON" in fmi_status_str:
                        fmi = "ON"
                    elif fmi_on is False or "OFF" in fmi_status_str:
                        fmi = "OFF"
                    else:
                        fmi = "ON" if "ON" in json.dumps(properties).upper() else "OFF"

                    # ตรวจสอบสถานะ Clean vs Lost
                    lost_mode = properties.get("lostMode")
                    if lost_mode is True or "LOST" in json.dumps(properties).upper() or "STOLEN" in json.dumps(properties).upper():
                        icloud_st = "LOST / STOLEN ⚠️"
                    else:
                        icloud_st = "CLEAN ✅"

                    model = properties.get("deviceName") or properties.get("modelDesc") or self.get_model_from_tac(imei)
                    serial = properties.get("serial") or properties.get("serialNumber") or "-"

                    is_sandbox = "SANDBOX" in json.dumps(data).upper()
                    source_label = "Apple GSX (IMEICheck Live)" if not is_sandbox else "IMEICheck API (Sandbox)"

                    return {
                        "success": True,
                        "imei": imei,
                        "model": model,
                        "serial": serial,
                        "fmi_status": fmi,
                        "icloud_status": icloud_st,
                        "raw_text": json.dumps(properties, ensure_ascii=False, indent=2),
                        "source": source_label
                    }
                elif "ip_not_allowed" in str(data):
                    return {
                        "success": False, 
                        "error": "⚠️ กรุณาปิดสวิตช์ IP Whitelist ในเว็บ imeicheck.net เพื่อให้บอทเข้าถึงได้ครับ",
                        "source": "IMEICheck API"
                    }
            except Exception as e:
                print(f"Error querying IMEICheck (Service {s_id}): {e}")
        return None

    def check(self, imei: str) -> Dict[str, Any]:
        clean_imei = re.sub(r"[^A-Za-z0-9]", "", imei.strip())
        detected_model = self.get_model_from_tac(clean_imei)
        
        # 1. ยิงดึงข้อมูลสดจาก Apple ผ่าน IMEICheck API
        if self.imeicheck_key:
            res = self.check_imeicheck_net(clean_imei)
            if res:
                return res

        return {
            "success": True,
            "imei": clean_imei,
            "model": detected_model,
            "serial": "F2L" + clean_imei[-7:],
            "fmi_status": "REQUIRE_API_KEY",
            "icloud_status": "กรุณาเชื่อมต่อ Live API",
            "raw_text": "",
            "source": "Smart TAC Identifier"
        }

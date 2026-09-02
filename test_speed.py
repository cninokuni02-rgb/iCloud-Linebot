import time
import httpx
import asyncio

async def run_server_speedtest():
    results = {}
    async with httpx.AsyncClient(timeout=30) as client:
        # 1. วัด Ping / Latency
        t0 = time.perf_counter()
        await client.get("https://1.1.1.1")
        ping_ms = (time.perf_counter() - t0) * 1000
        results["ping_ms"] = round(ping_ms, 2)

        # 2. วัด Download Speed (ดาวน์โหลดไฟล์ทดสอบ 10MB จาก Cloudflare)
        url_download = "https://speed.cloudflare.com/__down?bytes=10000000"
        t0 = time.perf_counter()
        res_down = await client.get(url_download)
        duration_down = time.perf_counter() - t0
        bytes_len = len(res_down.content)
        download_mbps = (bytes_len * 8) / (duration_down * 1_000_000)
        results["download_mbps"] = round(download_mbps, 2)
        results["download_duration_sec"] = round(duration_down, 2)

        # 3. วัด Upload Speed (อัปโหลด 5MB)
        url_upload = "https://speed.cloudflare.com/__up"
        dummy_data = b"0" * 5000000
        t0 = time.perf_counter()
        await client.post(url_upload, content=dummy_data)
        duration_up = time.perf_counter() - t0
        upload_mbps = (5000000 * 8) / (duration_up * 1_000_000)
        results["upload_mbps"] = round(upload_mbps, 2)
        results["upload_duration_sec"] = round(duration_up, 2)

    return results

print("Speedtest script ready")

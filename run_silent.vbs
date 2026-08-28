Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c python -m uvicorn app:app --host 127.0.0.1 --port 8000", 0, False
WshShell.Run "cmd /c .\cloudflared.exe tunnel --url http://127.0.0.1:8000", 0, False

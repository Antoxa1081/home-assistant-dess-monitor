import json
import websocket

url = "wss://web.dessmonitor.com/relay-ess/monitor/dataNew?devcode=2376&pn=Q0045214895160&devaddr=1&sn=Q0045214895160094801"

headers = [
    "Origin: https://www.dessmonitor.com",
    "Pragma: no-cache",
    "Cache-Control: no-cache",
    "User-Agent: Mozilla/5.0",
    "Accept-Language: en-US,en;q=0.9,ru;q=0.8,ja;q=0.7,uk;q=0.6",
]

def on_message(ws, message):
    print("RAW:", message)
    try:
        outer = json.loads(message)
        if isinstance(outer.get("data"), str):
            outer["data"] = json.loads(outer["data"])
        print(json.dumps(outer, ensure_ascii=False, indent=2))
    except Exception as e:
        print("parse error:", e)
def on_error(ws, error):
    print("error:", error)

def on_close(ws, close_status_code, close_msg):
    print("closed:", close_status_code, close_msg)

def on_open(ws):
    print("connected")

ws = websocket.WebSocketApp(
    url,
    header=headers,
    on_open=on_open,
    on_message=on_message,
    on_error=on_error,
    on_close=on_close,
)

ws.run_forever()
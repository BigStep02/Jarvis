import json
from collections import deque
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
import psutil
import httpx
import time as _time

_location_cache = None
_location_cache_ts = 0

def _load_settings():
    try:
        with open("settings.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

async def _get_location(client: httpx.AsyncClient):
    global _location_cache, _location_cache_ts

    settings = _load_settings()
    city_override = settings.get("city", "").strip()

    if city_override:
        # 도시명으로 좌표 조회 (Open-Meteo geocoding)
        if _location_cache and _location_cache.get("city_key") == city_override:
            return _location_cache
        r = await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city_override, "count": 1, "language": "en"},
            timeout=5,
        )
        results = r.json().get("results", [])
        if results:
            geo = results[0]
            _location_cache = {
                "lat": geo["latitude"],
                "lon": geo["longitude"],
                "city": geo.get("name", city_override),
                "country": geo.get("country_code", ""),
                "city_key": city_override,
            }
            return _location_cache

    # 설정 없으면 IP 기반 감지
    if _location_cache and _time.time() - _location_cache_ts < 3600:
        return _location_cache
    r = await client.get("http://ip-api.com/json/?fields=lat,lon,city,countryCode", timeout=5)
    data = r.json()
    _location_cache = {
        "lat": data["lat"],
        "lon": data["lon"],
        "city": data.get("city", ""),
        "country": data.get("countryCode", ""),
        "city_key": None,
    }
    _location_cache_ts = _time.time()
    return _location_cache

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

connected_clients: list[WebSocket] = []
command_queue: deque = deque()

@app.get("/")
async def root():
    with open("static/index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "text_command":
                command_queue.append(msg["text"])
                await broadcast({"type": "chat", "role": "user", "text": msg["text"]})
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)

class Event(BaseModel):
    type: str
    state: Optional[str] = None
    role: Optional[str] = None
    text: Optional[str] = None
    value: Optional[float] = None
    low: Optional[float] = None
    mid: Optional[float] = None
    high: Optional[float] = None

@app.get("/stats")
async def get_stats():
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    return {
        "cpu": cpu,
        "ram_used": round(mem.used / (1024 ** 3), 1),
        "ram_total": round(mem.total / (1024 ** 3), 1),
        "ram_pct": mem.percent,
        "disk_used": round(disk.used / (1024 ** 3), 1),
        "disk_total": round(disk.total / (1024 ** 3), 1),
        "disk_pct": disk.percent,
    }

@app.get("/weather")
async def get_weather():
    async with httpx.AsyncClient() as client:
        loc = await _get_location(client)
        params = {
            "latitude": loc["lat"],
            "longitude": loc["lon"],
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,weather_code",
            "wind_speed_unit": "ms",
        }
        r = await client.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=10)
    data = r.json()
    data["city"] = loc["city"]
    data["country"] = loc["country"]
    return data

@app.get("/poll")
async def poll_command():
    if command_queue:
        return {"command": command_queue.popleft()}
    return {"command": None}

@app.post("/event")
async def receive_event(event: Event):
    msg = {k: v for k, v in event.model_dump().items() if v is not None}
    await broadcast(msg)
    return {"ok": True}

async def broadcast(message: dict):
    dead = []
    for client in connected_clients:
        try:
            await client.send_json(message)
        except:
            dead.append(client)
    for c in dead:
        if c in connected_clients:
            connected_clients.remove(c)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
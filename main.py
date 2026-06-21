import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

connected_clients: list[WebSocket] = []

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
                await broadcast({"type": "chat", "role": "user", "text": msg["text"]})
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)

class Event(BaseModel):
    type: str
    state: Optional[str] = None
    role: Optional[str] = None
    text: Optional[str] = None

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
import os
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

connected_clients: list[WebSocket] = []

agents = {
    "agent01": {"name": "AI 뉴스 수집/요약", "status": "대기", "process": "대기중"},
    "agent02": {"name": "브리핑 에이전트", "status": "대기", "process": "대기중"},
    "agent03": {"name": "스케줄 관리", "status": "대기", "process": "대기중"},
    "agent04": {"name": "자유 대화", "status": "활성", "process": "대기중"},
}

@app.get("/")
async def root():
    with open("static/index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    await websocket.send_json({"type": "agents", "data": agents})
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        connected_clients.remove(websocket)

async def broadcast(message: dict):
    for client in connected_clients:
        try:
            await client.send_json(message)
        except:
            pass

def update_agent(agent_id: str, status: str, process: str):
    agents[agent_id]["status"] = status
    agents[agent_id]["process"] = process
    asyncio.run(broadcast({"type": "agent_update", "id": agent_id, "data": agents[agent_id]}))

def send_message(role: str, text: str):
    asyncio.run(broadcast({"type": "message", "role": role, "text": text}))

def set_listening(is_listening: bool):
    asyncio.run(broadcast({"type": "listening", "value": is_listening}))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
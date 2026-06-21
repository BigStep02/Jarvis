const ws = new WebSocket("ws://127.0.0.1:8000/ws");

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  if (msg.type === "agents") {
    Object.entries(msg.data).forEach(([id, agent]) => updateAgentCard(id, agent));
  }

  if (msg.type === "agent_update") {
    updateAgentCard(msg.id, msg.data);
  }

  if (msg.type === "message") {
    addChatEntry(msg.role, msg.text);
  }

  if (msg.type === "listening") {
    setListening(msg.value);
  }
};

function updateAgentCard(id, agent) {
  const card = document.getElementById(id);
  if (!card) return;

  document.getElementById(`${id}-name`).textContent = agent.name;
  document.getElementById(`${id}-status`).textContent = agent.status;
  document.getElementById(`${id}-process`).textContent = agent.process;

  card.className = "agent-card";
  if (agent.status === "활성") card.classList.add("active");
  else if (agent.status === "오류") card.classList.add("error");
  else card.classList.add("waiting");

  const processEl = document.getElementById(`${id}-process`);
  processEl.className = "value" + (agent.status === "오류" ? " error" : "");
}

function addChatEntry(role, text) {
  const log = document.getElementById("chat-log");
  const entry = document.createElement("div");
  entry.className = "chat-entry";
  entry.innerHTML = `<span class="role">${role.toUpperCase()}</span><span class="text">${text}</span>`;
  log.appendChild(entry);
  log.scrollTop = log.scrollHeight;

  if (role === "나") {
    document.getElementById("input-text").textContent = text;
  }
}

function setListening(isListening) {
  document.getElementById("status-text").textContent = isListening ? "LISTENING..." : "STANDBY";
  document.getElementById("status-sub").textContent = isListening
    ? "명령을 말씀하세요."
    : "Awaiting your command, boss.";
}

// 시계
function updateClock() {
  const now = new Date();
  const h = String(now.getHours()).padStart(2, "0");
  const m = String(now.getMinutes()).padStart(2, "0");
  const s = String(now.getSeconds()).padStart(2, "0");
  document.getElementById("clock").textContent = `${h}:${m}:${s}`;
}
setInterval(updateClock, 1000);
updateClock();

// 연결 유지
setInterval(() => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "ping" }));
  }
}, 30000);

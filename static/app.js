// ─── Jarvis 상태 정의 ───
const STATE_COLORS = {
  standby:   { r: 0,   g: 212, b: 255 },
  listening: { r: 255, g: 80,  b: 80  },
  thinking:  { r: 180, g: 130, b: 255 },
  working:   { r: 255, g: 170, b: 30  },
  speaking:  { r: 0,   g: 230, b: 118 },
};

const stateLabels = {
  standby:   'Standby',
  listening: 'Listening...',
  thinking:  'Thinking...',
  speaking:  'Speaking...',
  working:   'Working...',
};

let currentState = 'standby';

// ─── 오디오 레벨 (speak() 중 백엔드가 실제 파형을 분석해서 보내줌) ───
let targetAudioLevel = 0, targetAudioLow = 0, targetAudioMid = 0, targetAudioHigh = 0;
let currentAudioLevel = 0, currentAudioLow = 0, currentAudioMid = 0, currentAudioHigh = 0;

// ─── WebSocket ───
const ws = new WebSocket('ws://127.0.0.1:8000/ws');

ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === 'status') setJarvisState(msg.state);
  if (msg.type === 'chat')   addChat(msg.role, msg.text);
  if (msg.type === 'audio_level') {
    targetAudioLevel = msg.value ?? 0;
    targetAudioLow   = msg.low   ?? 0;
    targetAudioMid   = msg.mid   ?? 0;
    targetAudioHigh  = msg.high  ?? 0;
  }
};

ws.onclose = () => {
  const el = document.getElementById('status-badge');
  if (el) el.textContent = 'DISCONNECTED';
};

function setJarvisState(state) {
  currentState = state;
  if (state !== 'speaking') {
    targetAudioLevel = 0;
    targetAudioLow = 0;
    targetAudioMid = 0;
    targetAudioHigh = 0;
  }

  const dot = document.getElementById('status-dot');
  if (dot) dot.className = `status-dot ${state}`;

  const detail = document.getElementById('status-detail');
  if (detail) detail.textContent = stateLabels[state] || state;
}

let cmdCount = 0;

function addChat(role, text) {
  if (role === 'user') {
    cmdCount++;
    const el = document.getElementById('cmd-count');
    if (el) el.textContent = cmdCount;
  }
  const log = document.getElementById('chat-log');
  const wrap = document.createElement('div');
  wrap.className = `bubble-wrap ${role}`;
  wrap.innerHTML = `
    <span class="bubble-role">${role === 'user' ? 'YOU' : 'JARVIS'}</span>
    <div class="bubble">${text}</div>
  `;
  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
}

// ─── 텍스트 입력 ───
// 한글 조합 중에 Enter가 오면 바로 보내지 않고 조합이 끝난 뒤에 보낸다.
// (조합 중 입력창을 비우면 브라우저가 마지막 글자를 다시 넣어서 한 글자가 중복 전송됨)
const textInput = document.getElementById('text-input');
let composing = false;
let sendAfterCompose = false;

textInput.addEventListener('compositionstart', () => { composing = true; });
textInput.addEventListener('compositionend', () => {
  composing = false;
  if (sendAfterCompose) {
    sendAfterCompose = false;
    setTimeout(sendText, 0);
  }
});
textInput.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter') return;
  // Chrome: 조합이 아직 안 끝난 상태로 Enter가 옴 → compositionend에서 전송
  if (composing || e.isComposing) { sendAfterCompose = true; return; }
  // Safari: 조합이 먼저 끝나고 keyCode 229로 Enter가 옴 → 확정된 값으로 바로 전송
  if (e.keyCode === 229) { setTimeout(sendText, 0); return; }
  e.preventDefault();
  sendText();
});
document.getElementById('send-btn').addEventListener('click', sendText);

let lastSent = '';
let lastSentAt = 0;

function sendText() {
  const input = textInput;
  const text = input.value.trim();
  input.value = '';
  if (!text) { input.focus(); return; }
  // 안전장치: 직전 전송의 마지막 글자 한 개가 바로 뒤따라오면 IME 잔여 글자로 보고 버린다
  if (text.length === 1 && lastSent.endsWith(text) && Date.now() - lastSentAt < 1500) {
    input.focus();
    return;
  }
  lastSent = text;
  lastSentAt = Date.now();
  ws.send(JSON.stringify({ type: 'text_command', text }));
  input.focus();
}

// ─── 시계 / 날짜 ───
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];

function updateClock() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const h = now.getHours();
  const ampm = h >= 12 ? 'PM' : 'AM';
  const h12 = h % 12 || 12;
  document.getElementById('clock').textContent =
    `${pad(h12)}:${pad(now.getMinutes())}:${pad(now.getSeconds())} ${ampm}`;
  document.getElementById('date').textContent =
    `${MONTHS[now.getMonth()]} ${now.getDate()}, ${now.getFullYear()}`;
}
setInterval(updateClock, 1000);
updateClock();

// ─── 업타임 카운터 ───
const startTime = Date.now();
function updateUptime() {
  const sec = Math.floor((Date.now() - startTime) / 1000);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const pad = (n) => String(n).padStart(2, '0');
  const el = document.getElementById('uptime');
  if (el) el.textContent = `${pad(h)}:${pad(m)}:${pad(s)}`;
}
setInterval(updateUptime, 1000);
updateUptime();

// ============================================================
//  PARTICLE CLOUD (2D Canvas)
// ============================================================
const pCanvas = document.getElementById('particleCanvas');
const pCtx = pCanvas.getContext('2d');
const PARTICLE_COUNT = 420;
const CONNECTION_DIST = 52;
const PCANVAS_SIZE = 760;
const PCANVAS_CENTER = PCANVAS_SIZE / 2;
const PCANVAS_MAXR = PCANVAS_SIZE / 2 - 20;
const particles = [];

function resizeParticleCanvas() {
  const dpr = window.devicePixelRatio || 1;
  const displaySize = 500;
  pCanvas.style.width = displaySize + 'px';
  pCanvas.style.height = displaySize + 'px';
  pCanvas.width = PCANVAS_SIZE * dpr;
  pCanvas.height = PCANVAS_SIZE * dpr;
  pCtx.setTransform(1, 0, 0, 1, 0, 0);
  pCtx.scale(dpr, dpr);
}
resizeParticleCanvas();
window.addEventListener('resize', resizeParticleCanvas);

// 밀도 falloff로 중심에 몰리는 "구름" 형태 배치
for (let i = 0; i < PARTICLE_COUNT; i++) {
  const angle = Math.random() * Math.PI * 2;
  const radius = 18 + Math.pow(Math.random(), 0.6) * 150;
  const depth = 0.3 + Math.random() * 0.7;
  const hot = Math.random() < 0.06;
  particles.push({
    x: PCANVAS_CENTER + Math.cos(angle) * radius,
    y: PCANVAS_CENTER + Math.sin(angle) * radius,
    baseAngle: angle,
    baseRadius: radius,
    depth,
    hot,
    size: (0.5 + Math.random() * 1.4) * depth,
    speed: 0.2 + Math.random() * 0.5,
    phase: Math.random() * Math.PI * 2,
    driftSeedX: Math.random() * 1000,
    driftSeedY: Math.random() * 1000,
    driftSpeedX: 0.10 + Math.random() * 0.22,
    driftSpeedY: 0.10 + Math.random() * 0.22,
    driftAmp: 6 + Math.random() * 10,
    burst: 0,
    burstGain: 0.6 + Math.random() * 0.9,
  });
}

let animTime = 0;

function animateParticles(timestamp) {
  animTime = timestamp * 0.001;
  currentAudioLevel += (targetAudioLevel - currentAudioLevel) * 0.30;
  currentAudioLow   += (targetAudioLow   - currentAudioLow)   * 0.28;
  currentAudioMid   += (targetAudioMid   - currentAudioMid)   * 0.32;
  currentAudioHigh  += (targetAudioHigh  - currentAudioHigh)  * 0.35;

  const cx = PCANVAS_CENTER, cy = PCANVAS_CENTER;
  const col = STATE_COLORS[currentState] || STATE_COLORS.standby;

  // 잔상 트레일: 완전히 지우지 않고 이전 프레임을 서서히 페이드아웃
  pCtx.globalCompositeOperation = 'destination-out';
  pCtx.fillStyle = 'rgba(0,0,0,0.28)';
  pCtx.fillRect(0, 0, PCANVAS_SIZE, PCANVAS_SIZE);
  pCtx.globalCompositeOperation = 'source-over';

  for (let i = 0; i < PARTICLE_COUNT; i++) {
    const p = particles[i];
    const t = animTime;

    switch (currentState) {
      case 'standby': {
        // 살아있는 구름: 각 파티클이 독립적으로 자기 앵커 주변을 부유
        const breathe = Math.sin(t * 0.55 + p.phase) * 0.06 + 1.0;
        const ax = cx + Math.cos(p.baseAngle) * p.baseRadius * breathe;
        const ay = cy + Math.sin(p.baseAngle) * p.baseRadius * breathe;
        const dx = (Math.sin(t * p.driftSpeedX + p.driftSeedX)
                  + Math.sin(t * p.driftSpeedX * 0.47 + p.driftSeedX * 1.7) * 0.5)
                  * p.driftAmp;
        const dy = (Math.cos(t * p.driftSpeedY + p.driftSeedY)
                  + Math.cos(t * p.driftSpeedY * 0.53 + p.driftSeedY * 1.3) * 0.5)
                  * p.driftAmp;
        const tx = ax + dx;
        const ty = ay + dy;
        p.x += (tx - p.x) * 0.03;
        p.y += (ty - p.y) * 0.03;
        p.burst += (0 - p.burst) * 0.08;
        break;
      }
      case 'listening': {
        // 실시간 마이크 레벨은 아직 없어서, 리듬감 있는 시뮬레이션 펄스로 대체
        const breathe = Math.sin(t * 0.55 + p.phase) * 0.06 + 1.0;
        const ax = cx + Math.cos(p.baseAngle) * p.baseRadius * breathe;
        const ay = cy + Math.sin(p.baseAngle) * p.baseRadius * breathe;
        const wx = Math.sin(t * p.driftSpeedX + p.driftSeedX) * p.driftAmp * 0.5;
        const wy = Math.cos(t * p.driftSpeedY + p.driftSeedY) * p.driftAmp * 0.5;
        const pulse = (Math.sin(t * 3.4 + p.phase) * 0.5 + 0.5) * 26;
        const targetBurst = pulse * p.burstGain;
        p.burst += (targetBurst - p.burst) * 0.22;
        const r = p.baseRadius * breathe + p.burst;
        const tx = cx + Math.cos(p.baseAngle) * r + wx;
        const ty = cy + Math.sin(p.baseAngle) * r + wy;
        p.x += (tx - p.x) * 0.12;
        p.y += (ty - p.y) * 0.12;
        break;
      }
      case 'thinking':
      case 'working': {
        // 나선형 궤도 — 생각하는 느낌
        const spiral = Math.sin(t * 1.5 + p.phase) * 0.3 + 1.0;
        const a = p.baseAngle + t * p.speed * 0.7 + Math.sin(t * 0.5) * 0.3;
        const r = p.baseRadius * spiral + Math.sin(t * 2.5 + p.phase) * 15;
        p.x += (cx + Math.cos(a) * r - p.x) * 0.035;
        p.y += (cy + Math.sin(a) * r - p.y) * 0.035;
        break;
      }
      case 'speaking': {
        // 말하기: 실제 TTS 파형(currentAudioLevel/Low/Mid/High)에 맞춰 바깥으로 튐
        const breathe = Math.sin(t * 0.6 + p.phase) * 0.07 + 1.0;
        const wx = Math.sin(t * p.driftSpeedX + p.driftSeedX) * p.driftAmp * 0.5;
        const wy = Math.cos(t * p.driftSpeedY + p.driftSeedY) * p.driftAmp * 0.5;
        const bandMix = 0.5 + 0.5 * Math.sin(p.phase * 1.9);
        const basePulse = Math.pow(Math.sin(t * 3.2 + p.phase * 0.5), 2) * 8;
        const audioDrive = currentAudioLevel * (40 + bandMix * 20)
                          + currentAudioLow * 15 + currentAudioMid * 10
                          + currentAudioHigh * bandMix * 12;
        const targetBurst = Math.min(80, (basePulse + audioDrive) * p.burstGain);
        p.burst += (targetBurst - p.burst) * 0.26;
        const r = p.baseRadius * breathe + p.burst;
        const tx = cx + Math.cos(p.baseAngle) * r + wx;
        const ty = cy + Math.sin(p.baseAngle) * r + wy;
        p.x += (tx - p.x) * 0.10;
        p.y += (ty - p.y) * 0.10;
        p.x += Math.sin(t * 6 + p.phase) * currentAudioHigh * 2;
        p.y += Math.cos(t * 5 + p.phase) * currentAudioHigh * 2;
        break;
      }
    }

    // 원형 경계 — 벗어나면 부드럽게 안으로 당김
    const ox = p.x - cx, oy = p.y - cy;
    const odist = Math.sqrt(ox * ox + oy * oy);
    if (odist > PCANVAS_MAXR) {
      const pull = (odist - PCANVAS_MAXR) * 0.25;
      const nx = ox / odist, ny = oy / odist;
      p.x -= nx * pull;
      p.y -= ny * pull;
    }
  }

  // 연결선 (별자리 효과)
  const connDist = currentState === 'listening' ? 64 : currentState === 'speaking' ? 58 : CONNECTION_DIST;
  const connDistSq = connDist * connDist;
  const lineAlphaBase = currentState === 'standby' ? 0.06 : 0.08;

  pCtx.lineWidth = currentState === 'speaking' ? 0.8 : 0.5;
  for (let i = 0; i < PARTICLE_COUNT; i++) {
    const pi = particles[i];
    for (let j = i + 1; j < PARTICLE_COUNT; j++) {
      const pj = particles[j];
      const dx = pi.x - pj.x;
      const dy = pi.y - pj.y;
      const distSq = dx * dx + dy * dy;
      if (distSq < connDistSq) {
        const dist = Math.sqrt(distSq);
        const depthFade = (pi.depth + pj.depth) * 0.5;
        const alpha = (1 - dist / connDist) * lineAlphaBase * depthFade;
        pCtx.strokeStyle = `rgba(${col.r},${col.g},${col.b},${alpha})`;
        pCtx.beginPath();
        pCtx.moveTo(pi.x, pi.y);
        pCtx.lineTo(pj.x, pj.y);
        pCtx.stroke();
      }
    }
  }

  // 파티클 렌더 — depth로 크기/알파를 나눠 층이 있는 것처럼 보이게
  const audioGlow = currentState === 'speaking' ? currentAudioLevel : 0;
  for (let i = 0; i < PARTICLE_COUNT; i++) {
    const p = particles[i];
    const burstAmt = Math.min(1, p.burst / 60);
    let glow, sz;
    switch (currentState) {
      case 'speaking':
        glow = (0.5 + audioGlow * 0.35 + burstAmt * 0.3) * p.depth;
        sz = p.size * (1 + burstAmt * 0.7);
        break;
      case 'listening':
        glow = (0.55 + burstAmt * 0.3) * p.depth;
        sz = p.size * (1 + burstAmt * 0.6);
        break;
      default:
        glow = (0.35 + 0.25 * p.depth) * p.depth;
        sz = p.size;
    }
    if (p.hot) {
      pCtx.shadowBlur = 6 + p.depth * 6 + audioGlow * 6;
      pCtx.shadowColor = `rgba(${col.r},${col.g},${col.b},${0.5 * p.depth})`;
      glow = Math.min(1, glow + 0.35);
    } else {
      pCtx.shadowBlur = (2 + audioGlow * 6) * p.depth;
      pCtx.shadowColor = `rgba(${col.r},${col.g},${col.b},${0.3 * p.depth})`;
    }
    pCtx.fillStyle = `rgba(${col.r},${col.g},${col.b},${Math.min(1, glow)})`;
    pCtx.beginPath();
    pCtx.arc(p.x, p.y, Math.max(0.3, sz), 0, Math.PI * 2);
    pCtx.fill();
  }
  pCtx.shadowBlur = 0;

  // 중심 코어 글로우 — 오디오에 반응해서 밝아짐
  const coreBase = currentState === 'standby' ? 0.05 : 0.08;
  const coreAlpha = coreBase + audioGlow * 0.18;
  if (coreAlpha > 0.01) {
    const coreR = 70 + audioGlow * 40;
    const grad = pCtx.createRadialGradient(cx, cy, 0, cx, cy, coreR);
    grad.addColorStop(0, `rgba(${col.r},${col.g},${col.b},${coreAlpha})`);
    grad.addColorStop(1, `rgba(${col.r},${col.g},${col.b},0)`);
    pCtx.fillStyle = grad;
    pCtx.beginPath();
    pCtx.arc(cx, cy, coreR, 0, Math.PI * 2);
    pCtx.fill();
  }

  requestAnimationFrame(animateParticles);
}
requestAnimationFrame(animateParticles);

// ─── System Stats 폴링 ───
async function pollStats() {
  try {
    const r = await fetch('/stats');
    const d = await r.json();

    document.getElementById('cpu-val').textContent  = d.cpu.toFixed(1) + '%';
    document.getElementById('cpu-bar').style.width  = d.cpu + '%';
    document.getElementById('cpu-pct').textContent  = d.cpu.toFixed(1) + '%';
    document.getElementById('ram-val').textContent  = d.ram_used + ' / ' + d.ram_total + ' GB';
    document.getElementById('ram-bar').style.width  = d.ram_pct + '%';
    document.getElementById('mem-pct').textContent  = d.ram_pct.toFixed(1) + '%';
    document.getElementById('disk-val').textContent = d.disk_used + '/' + d.disk_total + 'G';

    const load = d.cpu;
    const loadBadge = document.getElementById('load-badge');
    const loadBar   = document.getElementById('load-bar');
    loadBar.style.width = load + '%';
    if (load < 40) { loadBadge.textContent = 'Normal';   loadBadge.className = 'load-badge'; }
    else if (load < 75) { loadBadge.textContent = 'Medium'; loadBadge.className = 'load-badge warn'; }
    else { loadBadge.textContent = 'High'; loadBadge.className = 'load-badge danger'; }
  } catch (_) {}
}
pollStats();
setInterval(pollStats, 3000);

// ─── Weather ───
const WX_ICONS = {
  0: '☀️', 1: '🌤', 2: '⛅', 3: '☁️',
  45: '🌫', 48: '🌫',
  51: '🌦', 53: '🌦', 55: '🌦',
  61: '🌧', 63: '🌧', 65: '🌧',
  71: '🌨', 73: '🌨', 75: '🌨',
  80: '🌦', 81: '🌦', 82: '🌦',
  95: '⛈',
};
const WX_DESC = {
  0: '맑음', 1: '대체로 맑음', 2: '구름 조금', 3: '흐림',
  45: '안개', 48: '안개',
  51: '이슬비', 53: '이슬비', 55: '이슬비',
  61: '비', 63: '비', 65: '강한 비',
  71: '눈', 73: '눈', 75: '강한 눈',
  80: '소나기', 81: '소나기', 82: '강한 소나기',
  95: '뇌우',
};

async function fetchWeather() {
  try {
    const r = await fetch('/weather');
    const d = await r.json();
    const c = d.current;
    const code = c.weather_code;
    const city = d.city || 'Unknown';
    const country = d.country || '';
    document.getElementById('w-temp').textContent  = c.temperature_2m.toFixed(1) + '°C';
    document.getElementById('w-desc').textContent  = WX_DESC[code] ?? '—';
    document.getElementById('w-hum').textContent   = c.relative_humidity_2m + '%';
    document.getElementById('w-wind').textContent  = c.wind_speed_10m.toFixed(1) + ' m/s';
    document.getElementById('w-feel').textContent  = c.apparent_temperature.toFixed(1) + '°C';
    document.getElementById('w-loc').textContent   = city + (country ? ', ' + country : '');
    document.querySelector('.weather-icon').textContent = WX_ICONS[code] ?? '🌡';
    document.querySelector('.temp-badge').textContent   = '🌡 ' + c.temperature_2m.toFixed(1) + '°C ' + city;
  } catch (_) {}
}
fetchWeather();
setInterval(fetchWeather, 10 * 60 * 1000);

// 콘솔 테스트용
window.setState = setJarvisState;

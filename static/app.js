import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { GammaCorrectionShader } from 'three/addons/shaders/GammaCorrectionShader.js';

// ─── Jarvis 상태 정의 ───
const STATE_COLORS = {
  standby:   0x4fc3f7,
  listening: 0xef5350,
  thinking:  0xab47bc,
  speaking:  0x4caf50,
  working:   0xff9800,
};

const STATE_SHAPES = {
  standby:   'sphere',
  listening: 'torus',
  thinking:  'torus',
  speaking:  'torus',
  working:   'torus',
};

const stateLabels = {
  standby:   'Standby',
  listening: 'Listening...',
  thinking:  'Thinking...',
  speaking:  'Speaking...',
  working:   'Working...',
};

let currentState = 'standby';

// ─── WebSocket ───
const ws = new WebSocket('ws://127.0.0.1:8000/ws');

ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === 'status') setJarvisState(msg.state);
  if (msg.type === 'chat')   addChat(msg.role, msg.text);
};

ws.onclose = () => {
  document.getElementById('status-badge').textContent = 'DISCONNECTED';
};

function setJarvisState(state) {
  currentState = state;
  params.particleColor = STATE_COLORS[state] ?? STATE_COLORS.standby;
  if (particleSystem) particleSystem.material.opacity = state === 'standby' ? 0.25 : 0.07;
  updateParticleSystem();
  morphToShape(STATE_SHAPES[state] ?? 'sphere');
  pulsePhase = 0;
  regenerateScatter();

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
document.getElementById('send-btn').addEventListener('click', sendText);
document.getElementById('text-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendText();
});

function sendText() {
  const input = document.getElementById('text-input');
  const text = input.value.trim();
  if (!text) return;
  ws.send(JSON.stringify({ type: 'text_command', text }));
  input.value = '';
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

// particle orb
const container = document.getElementById('sphere-container');

let scene, camera, renderer, controls, particleSystem, lineSystem;
const numParticles = 600;
const LINE_THRESHOLD = 0.28;
const MAX_LINES = 30000;
const clock = new THREE.Clock();
let targetPositions = [];
let animationProgress = 1;
const animationDuration = 1.5;
let pulsePhase = 0;
let pulseSpeedPhase = 0;
let orbitTime = 0;
let currentScatterT = 0;
let scatterPositions = null;
let particleSpeeds = null;
let composer, bloomPass;
let trailTexture, trailScene, trailCamera, trailComposer;

const params = {
  particleSize:   0.035,
  particleColor:  0x4fc3f7,
  rotationSpeed:  0.04,
  bloomStrength:  0.0,
  bloomRadius:    0.0,
  bloomThreshold: 1.0,
  motionTrail:    0.3,
};

init();
animate();

function init() {
  initScenes();
  initComposers();
  initControls();
  createParticleSystem();
  createLineSystem();
  initTrailEffect();
  morphToShape('sphere');
  window.addEventListener('resize', onWindowResize);
}

function initScenes() {
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0e14);

  camera = new THREE.PerspectiveCamera(60, container.clientWidth / container.clientHeight, 0.1, 1000);
  camera.position.z = 5;

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1;
  container.appendChild(renderer.domElement);

  trailScene = new THREE.Scene();
  trailCamera = camera.clone();
  trailTexture = new THREE.WebGLRenderTarget(container.clientWidth, container.clientHeight, {
    minFilter: THREE.LinearFilter,
    magFilter: THREE.LinearFilter,
    format: THREE.RGBAFormat,
  });
}

function initComposers() {
  composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));

  bloomPass = new UnrealBloomPass(
    new THREE.Vector2(container.clientWidth, container.clientHeight),
    params.bloomStrength, params.bloomRadius, params.bloomThreshold
  );
  composer.addPass(bloomPass);
  composer.addPass(new ShaderPass(GammaCorrectionShader));

  trailComposer = new EffectComposer(renderer, trailTexture);
  trailComposer.addPass(new RenderPass(trailScene, trailCamera));
}

function initControls() {
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.1;
  controls.rotateSpeed = 0.5;
  controls.minDistance = 2;
  controls.maxDistance = 10;
}

function createParticleSystem() {
  const geometry = new THREE.BufferGeometry();
  const positions = new Float32Array(numParticles * 3);
  const colors    = new Float32Array(numParticles * 3);
  const sizes     = new Float32Array(numParticles);

  targetPositions = new Float32Array(numParticles * 3);

  for (let i = 0; i < numParticles; i++) {
    // 중앙 30% 비우고 바깥쪽에 분포
    const r     = (0.85 + Math.random() * 0.15) * 1.1;
    const phi   = Math.acos(2 * Math.random() - 1);
    const theta = Math.random() * Math.PI * 2;
    const x = r * Math.sin(phi) * Math.cos(theta);
    const y = r * Math.sin(phi) * Math.sin(theta);
    const z = r * Math.cos(phi);

    positions[i*3]   = x;
    positions[i*3+1] = y;
    positions[i*3+2] = z;

    targetPositions[i*3]   = x;
    targetPositions[i*3+1] = y;
    targetPositions[i*3+2] = z;

    const color = new THREE.Color(params.particleColor);
    color.offsetHSL(0, 0, (Math.random() - 0.5) * 0.5);
    colors[i*3]   = color.r;
    colors[i*3+1] = color.g;
    colors[i*3+2] = color.b;

    sizes[i] = params.particleSize * (0.8 + Math.random() * 0.4);
  }

  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('color',    new THREE.BufferAttribute(colors, 3));
  geometry.setAttribute('size',     new THREE.BufferAttribute(sizes, 1));

  const material = new THREE.PointsMaterial({
    size: params.particleSize,
    vertexColors: true,
    blending: THREE.AdditiveBlending,
    depthTest: true,
    depthWrite: false,
    transparent: true,
    opacity: 0.25,
    sizeAttenuation: true,
  });

  particleSystem = new THREE.Points(geometry, material);
  scene.add(particleSystem);

  scatterPositions = new Float32Array(numParticles * 3);

  particleSpeeds = new Float32Array(numParticles);
  for (let i = 0; i < numParticles; i++) {
    particleSpeeds[i] = 0.5 + Math.random() * 1.2; // 0.5 ~ 1.7 배속
  }

  const trailParticles = particleSystem.clone();
  trailScene.add(trailParticles);
}

function createLineSystem() {
  const geo = new THREE.BufferGeometry();
  const linPos = new Float32Array(MAX_LINES * 6);
  const linCol = new Float32Array(MAX_LINES * 6);
  geo.setAttribute('position', new THREE.BufferAttribute(linPos, 3));
  geo.setAttribute('color',    new THREE.BufferAttribute(linCol, 3));
  geo.setDrawRange(0, 0);

  const mat = new THREE.LineBasicMaterial({
    vertexColors: true,
    blending: THREE.AdditiveBlending,
    transparent: true,
    depthWrite: false,
    opacity: 0.6,
  });

  lineSystem = new THREE.LineSegments(geo, mat);
  particleSystem.add(lineSystem);
}

function updateLines() {
  if (!lineSystem || !particleSystem) return;

  // standby: 항상 선 보임 / active: scatter 정도에 따라 나타났다 사라짐
  let lineOpacity;
  if (currentState === 'standby') {
    lineOpacity = 0.6;
  } else {
    const minT = 0.22;
    lineOpacity = 0.12 + Math.max(0, (currentScatterT - minT - 0.05) / 0.3) * 0.4;
  }
  lineSystem.material.opacity = lineOpacity;
  if (lineOpacity === 0) {
    lineSystem.geometry.setDrawRange(0, 0);
    return;
  }

  const pos  = particleSystem.geometry.attributes.position.array;
  const lPos = lineSystem.geometry.attributes.position.array;
  const lCol = lineSystem.geometry.attributes.color.array;
  const c    = new THREE.Color(params.particleColor);
  let count  = 0;

  for (let i = 0; i < numParticles && count < MAX_LINES; i++) {
    for (let j = i + 1; j < numParticles && count < MAX_LINES; j++) {
      const dx = pos[i*3] - pos[j*3];
      const dy = pos[i*3+1] - pos[j*3+1];
      const dz = pos[i*3+2] - pos[j*3+2];
      const dist = Math.sqrt(dx*dx + dy*dy + dz*dz);
      if (dist < LINE_THRESHOLD) {
        const alpha = (1 - dist / LINE_THRESHOLD) * 0.5;
        const base  = count * 6;
        lPos[base]   = pos[i*3];   lPos[base+1] = pos[i*3+1]; lPos[base+2] = pos[i*3+2];
        lPos[base+3] = pos[j*3];   lPos[base+4] = pos[j*3+1]; lPos[base+5] = pos[j*3+2];
        lCol[base]   = c.r*alpha;  lCol[base+1] = c.g*alpha;  lCol[base+2] = c.b*alpha;
        lCol[base+3] = c.r*alpha;  lCol[base+4] = c.g*alpha;  lCol[base+5] = c.b*alpha;
        count++;
      }
    }
  }

  lineSystem.geometry.setDrawRange(0, count * 2);
  lineSystem.geometry.attributes.position.needsUpdate = true;
  lineSystem.geometry.attributes.color.needsUpdate    = true;
}

function regenerateScatter() {
  if (!scatterPositions) return;
  for (let i = 0; i < numParticles; i++) {
    const dist = 0.3 + Math.random() * 0.6;
    const phi   = Math.acos(2 * Math.random() - 1);
    const theta = Math.random() * Math.PI * 2;
    scatterPositions[i*3]   = targetPositions[i*3]   + dist * Math.sin(phi) * Math.cos(theta);
    scatterPositions[i*3+1] = targetPositions[i*3+1] + dist * Math.sin(phi) * Math.sin(theta);
    scatterPositions[i*3+2] = targetPositions[i*3+2] + dist * Math.cos(phi);
  }
}

function initTrailEffect() {
  const trailMaterial = new THREE.ShaderMaterial({
    uniforms: { tDiffuse: { value: null }, opacity: { value: 0.9 } },
    vertexShader: `
      varying vec2 vUv;
      void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }
    `,
    fragmentShader: `
      uniform sampler2D tDiffuse;
      uniform float opacity;
      varying vec2 vUv;
      void main() { gl_FragColor = opacity * texture2D(tDiffuse, vUv); }
    `,
  });
  const trailPass = new ShaderPass(trailMaterial);
  trailPass.renderToScreen = true;
  composer.addPass(trailPass);
}

function morphToShape(shapeType) {
  let targetGeometry;
  let targetVertices = [];

  switch (shapeType) {
    case 'sphere':
      // 표면이 아닌 내부를 꽉 채우는 volumetric 분포
      for (let i = 0; i < numParticles; i++) {
        const r     = (0.85 + Math.random() * 0.15) * 0.75;
        const phi   = Math.acos(2 * Math.random() - 1);
        const theta = Math.random() * Math.PI * 2;
        targetPositions[i*3]   = r * Math.sin(phi) * Math.cos(theta);
        targetPositions[i*3+1] = r * Math.sin(phi) * Math.sin(theta);
        targetPositions[i*3+2] = r * Math.cos(phi);
      }
      animationProgress = 0;
      return;
    case 'cube':
      targetGeometry = new THREE.BoxGeometry(2.2, 2.2, 2.2); break;
    case 'torus':
      targetGeometry = new THREE.TorusGeometry(0.4, 0.16, 32, 150); break;
    case 'icosahedron':
      targetGeometry = new THREE.IcosahedronGeometry(1.7, 3); break;
    default: return;
  }

  targetGeometry.computeVertexNormals();
  const attr = targetGeometry.getAttribute('position');
  for (let i = 0; i < attr.count; i++) {
    const v = new THREE.Vector3();
    v.fromBufferAttribute(attr, i);
    targetVertices.push(v);
  }

  for (let i = 0; i < numParticles; i++) {
    const v = targetVertices[i % targetVertices.length];
    targetPositions[i*3]   = v.x;
    targetPositions[i*3+1] = v.y;
    targetPositions[i*3+2] = v.z;
  }

  animationProgress = 0;
  targetGeometry.dispose();
}

function updateParticleSystem() {
  if (!particleSystem) return;
  const colors = particleSystem.geometry.attributes.color.array;
  const sizes  = particleSystem.geometry.attributes.size.array;

  for (let i = 0; i < numParticles; i++) {
    const color = new THREE.Color(params.particleColor);
    color.offsetHSL(0, 0, (Math.random() - 0.5) * 0.5);
    colors[i*3]   = color.r;
    colors[i*3+1] = color.g;
    colors[i*3+2] = color.b;
    sizes[i] = params.particleSize * (0.8 + Math.random() * 0.4);
  }
  particleSystem.geometry.attributes.color.needsUpdate = true;
  particleSystem.geometry.attributes.size.needsUpdate  = true;
  particleSystem.material.size = params.particleSize;
}

function onWindowResize() {
  const w = container.clientWidth, h = container.clientHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
  composer.setSize(w, h);
  trailTexture.setSize(w, h);
  trailComposer.setSize(w, h);
}

function animate() {
  requestAnimationFrame(animate);
  const delta = clock.getDelta();
  orbitTime += delta;

  if (particleSystem) {
    const isActive  = currentState === 'listening' || currentState === 'speaking' || currentState === 'thinking' || currentState === 'working';
    const hasPulse  = currentState === 'listening' || currentState === 'speaking' || currentState === 'thinking' || currentState === 'working';

    if (isActive) {
      particleSystem.rotation.x = 0;
      particleSystem.rotation.y = 0;
      particleSystem.rotation.z -= delta * 0.5;

      if (hasPulse) {
        pulseSpeedPhase += delta * 0.6;
        pulsePhase += delta * 4.0;

        if (animationProgress >= 1 && scatterPositions) {
          const amp    = 0.2 + 0.4 * Math.abs(Math.sin(pulseSpeedPhase * 0.4));
          const minAmp = 0.22 + 0.1 * Math.abs(Math.sin(pulseSpeedPhase * 0.7));
          const positions = particleSystem.geometry.attributes.position.array;
          for (let i = 0; i < numParticles; i++) {
            const dx = targetPositions[i*3];
            const dy = targetPositions[i*3+1];
            const dz = targetPositions[i*3+2];
            const dist = Math.sqrt(dx*dx + dy*dy + dz*dz);
            const lag = (0.56 - dist) * 3.5;
            const spd = particleSpeeds ? particleSpeeds[i] : 1;
            const pt = minAmp + (1 - Math.cos(pulsePhase * spd - lag)) / 2 * amp;
            positions[i*3]   = targetPositions[i*3]   + (scatterPositions[i*3]   - targetPositions[i*3])   * pt;
            positions[i*3+1] = targetPositions[i*3+1] + (scatterPositions[i*3+1] - targetPositions[i*3+1]) * pt;
            positions[i*3+2] = targetPositions[i*3+2] + (scatterPositions[i*3+2] - targetPositions[i*3+2]) * pt;
            if (i === 0) currentScatterT = pt;
            // 위성 궤도: 파티클마다 다른 속도·위상·기울기로 작은 원을 그림
            const orbitPhase = (i / numParticles) * Math.PI * 6 + orbitTime * spd;
            const tilt = (i * 2.618) % (Math.PI * 2);
            const r = 0.018 + spd * 0.008;
            positions[i*3]   += Math.cos(orbitPhase) * r;
            positions[i*3+1] += Math.sin(orbitPhase) * Math.cos(tilt) * r;
            positions[i*3+2] += Math.sin(orbitPhase) * Math.sin(tilt) * r;
          }
          particleSystem.geometry.attributes.position.needsUpdate = true;
        }
      }
    } else {
      // standby: 맥동 없이 천천히 회전
      particleSystem.rotation.y += delta * params.rotationSpeed;
    }

    if (animationProgress < 1) {
      animationProgress += delta / animationDuration;
      animationProgress = Math.min(animationProgress, 1);

      const positions = particleSystem.geometry.attributes.position.array;
      for (let i = 0; i < numParticles * 3; i++) {
        positions[i] += (targetPositions[i] - positions[i]) * (delta / animationDuration);
      }
      particleSystem.geometry.attributes.position.needsUpdate = true;
    }
  }

  updateLines();

  renderer.setRenderTarget(trailTexture);
  renderer.render(scene, camera);
  renderer.setRenderTarget(null);

  controls.update();
  composer.render();
}

// 콘솔 테스트용
window.setState = setJarvisState;

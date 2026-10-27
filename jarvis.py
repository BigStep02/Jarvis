import sys
import os
import io
import re
import platform
import json
import time
import threading
import logging
import subprocess
import asyncio
import requests

# Windows 콘솔 기본 코드페이지(cp949)로는 em-dash 등 일부 유니코드 문자를
# print()할 때 UnicodeEncodeError로 죽는다. UTF-8로 강제 설정해 방지한다.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import av
import sounddevice as sd
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
import speech_recognition as sr
import pyaudio
import pyttsx3
import edge_tts
from faster_whisper import WhisperModel

# 설정
CLAUDE_CLI      = "claude.cmd" if platform.system() == "Windows" else "claude"
SERVER_URL      = "http://127.0.0.1:8000/event"
def _load_app_settings():
    try:
        with open("settings.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"whisper_model": "small"}

WHISPER_MODEL_SIZE = _load_app_settings().get("whisper_model", "small")
AUDIO_SR = 24000
AUDIO_LEVEL_REF = 4000.0
AUDIO_BAND_REF = {"low": 200000.0, "mid": 80000.0, "high": 30000.0}

def _get_wasapi_mic_index():
    # MME(기본) 장치는 Windows 볼륨 설정과 별개로 낮은 게인이 걸려있는 경우가 있어
    # 실제 시스템 볼륨이 반영되는 WASAPI 입력 장치를 우선 사용한다.
    try:
        pa = pyaudio.PyAudio()
        try:
            for i in range(pa.get_host_api_count()):
                info = pa.get_host_api_info_by_index(i)
                if info.get("name") == "Windows WASAPI":
                    idx = info.get("defaultInputDevice")
                    return idx if idx is not None and idx >= 0 else None
        finally:
            pa.terminate()
    except Exception as e:
        logging.warning(f"WASAPI 마이크 탐색 실패: {e}")
    return None

MIC_INDEX = _get_wasapi_mic_index() if platform.system() == "Windows" else None

HISTORY_FILE = "conversation_history.json"
MAX_HISTORY  = 6

WAKE_WORDS = ["자비스", "제이비스", "재비스"]
EXIT_WORDS = ["종료", "쉬어", "그만", "꺼져", "끝내", "닫아", "꺼"]

SYSTEM_PROMPT = """\
너는 자비스라는 AI 어시스턴트야. 간결하고 자연스럽게 한국어로 대답해줘.

도구 목록:
- open_app(name): PC에서 앱을 실행한다. 사용자가 앱을 열어달라고 하면 무조건 이 도구를 호출해라. 앱 이름을 모르더라도 그냥 시도해라.
- search_web(query): 웹에서 최신 정보를 검색한다. 모르는 정보, 최신 뉴스, 날씨, 주가, 실시간 정보가 필요할 때 사용해라.
- fetch_page(url): search_web으로 얻은 URL의 상세 페이지 내용을 가져온다.
- run_applescript(script): macOS AppleScript를 실행하고 결과를 돌려받는다. 앱 안의 동작이 필요할 때 사용해라.
  예) 볼륨: set volume output volume 50 / 음악: tell application "Music" to playpause
  예) 아이메시지: tell application "Messages" to send "내용" to participant "번호나 이메일" of (1st account whose service type = iMessage)
  예) 미리알림: tell application "Reminders" to make new reminder with properties {name:"내용"}
  예) 다크모드: tell application "System Events" to tell appearance preferences to set dark mode to not dark mode
  "do shell script"는 사용 금지. 메시지 전송처럼 되돌릴 수 없는 동작은 받는 사람과 내용이 분명할 때만 실행해라.

응답 형식 규칙:
- 도구 호출이 필요하면 tool_call 필드를 채우고 reply는 null로 남겨라.
- 도구 호출이 필요없으면 reply에 자연스러운 한국어 답변을 채우고 tool_call은 null로 남겨라.
- 대화 기록은 "사용자: ...", "자비스: ...", "[도구 결과 - 이름]: ..." 형식으로 주어진다."""

CLAUDE_JSON_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "reply": {"type": ["string", "null"]},
        "tool_call": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "properties": {
                        "name": {"const": "open_app"},
                        "args": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                            "required": ["name"],
                            "additionalProperties": False,
                        },
                    },
                    "required": ["name", "args"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "name": {"const": "search_web"},
                        "args": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                            "additionalProperties": False,
                        },
                    },
                    "required": ["name", "args"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "name": {"const": "fetch_page"},
                        "args": {
                            "type": "object",
                            "properties": {"url": {"type": "string"}},
                            "required": ["url"],
                            "additionalProperties": False,
                        },
                    },
                    "required": ["name", "args"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "name": {"const": "run_applescript"},
                        "args": {
                            "type": "object",
                            "properties": {"script": {"type": "string"}},
                            "required": ["script"],
                            "additionalProperties": False,
                        },
                    },
                    "required": ["name", "args"],
                    "additionalProperties": False,
                },
            ]
        },
    },
    "required": ["reply", "tool_call"],
    "additionalProperties": False,
}, ensure_ascii=False)

def get_app_commands():
    if platform.system() == "Windows":
        return {
            "chrome":     "start chrome",
            "notepad":    "start notepad",
            "explorer":   "start explorer",
            "calculator": "start calc",
            "vscode":     "code .",
        }
    else:
        return {
            "chrome":     "open -na \"Google Chrome\"",
            "notepad":    "open -a TextEdit",
            "explorer":   "open .",
            "calculator": "open -a Calculator",
            "vscode":     "code .",
        }

APPS = get_app_commands()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

VOICE = "ko-KR-InJoonNeural"
_tts_lock = threading.Lock()

# 대화 기록
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[-200:], f, ensure_ascii=False, indent=2)

conversation_history = load_history()

# UI 이벤트
def send_event(**kwargs):
    try:
        requests.post(SERVER_URL, json=kwargs, timeout=1)
    except:
        pass

def set_state(state):
    send_event(type="status", state=state)

def send_chat(role, text):
    send_event(type="chat", role=role, text=text)

# TTS
def _speak_pyttsx3(text):
    with _tts_lock:
        engine = pyttsx3.init()
        voices = engine.getProperty('voices')
        for v in voices:
            if 'male' in v.name.lower() or 'david' in v.name.lower() or 'mark' in v.name.lower():
                engine.setProperty('voice', v.id)
                break
        engine.setProperty('rate', 160)
        engine.setProperty('volume', 1.0)
        engine.say(text)
        engine.runAndWait()
        engine.stop()

async def _edge_tts_bytes(text):
    communicate = edge_tts.Communicate(text, VOICE)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()

def _decode_mp3_to_pcm(mp3_bytes):
    container = av.open(io.BytesIO(mp3_bytes))
    stream = container.streams.audio[0]
    resampler = av.AudioResampler(format="s16", layout="mono", rate=AUDIO_SR)
    frames = []
    for packet in container.demux(stream):
        for frame in packet.decode():
            for rframe in resampler.resample(frame):
                frames.append(rframe.to_ndarray())
    if not frames:
        return np.zeros(0, dtype=np.int16)
    return np.concatenate(frames, axis=1).flatten()

def _band_levels(chunk):
    fchunk = chunk.astype(np.float32)
    rms = float(np.sqrt(np.mean(fchunk ** 2)))
    windowed = fchunk * np.hanning(len(fchunk))
    fft = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(len(fchunk), d=1.0 / AUDIO_SR)

    def band(lo, hi, ref):
        mask = (freqs >= lo) & (freqs < hi)
        v = float(fft[mask].mean()) if mask.any() else 0.0
        return min(1.0, v / ref)

    return (
        min(1.0, rms / AUDIO_LEVEL_REF),
        band(50, 400, AUDIO_BAND_REF["low"]),
        band(400, 2000, AUDIO_BAND_REF["mid"]),
        band(2000, 8000, AUDIO_BAND_REF["high"]),
    )

def _play_pcm_with_levels(pcm):
    chunk_samples = int(AUDIO_SR * 0.05)
    sd.play(pcm, samplerate=AUDIO_SR, blocking=False)
    try:
        for start in range(0, len(pcm), chunk_samples):
            chunk = pcm[start:start + chunk_samples]
            if len(chunk) == 0:
                continue
            value, low, mid, high = _band_levels(chunk)
            send_event(type="audio_level", value=value, low=low, mid=mid, high=high)
            time.sleep(chunk_samples / AUDIO_SR)
        sd.wait()
    finally:
        send_event(type="audio_level", value=0, low=0, mid=0, high=0)

def _strip_markdown(text):
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', text)
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'^[-*]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n+', ' ', text)
    return text.strip()

def speak(text):
    text = _strip_markdown(text)
    print(f"자비스: {text}")
    set_state("speaking")
    send_chat("jarvis", text)

    try:
        mp3_bytes = asyncio.run(_edge_tts_bytes(text))
        pcm = _decode_mp3_to_pcm(mp3_bytes)
        if len(pcm) == 0:
            raise RuntimeError("빈 오디오 데이터")
        _play_pcm_with_levels(pcm)
    except Exception as e:
        logging.warning(f"edge-tts 재생 실패, pyttsx3 폴백: {e}")
        try:
            _speak_pyttsx3(text)
        except Exception as e2:
            logging.warning(f"speak 실패: {e2}")

    set_state("standby")

# STT
_whisper_lock = threading.Lock()
_current_model_size = WHISPER_MODEL_SIZE

logging.info(f"Whisper 모델 로딩 중... ({WHISPER_MODEL_SIZE})")
_whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
logging.info("Whisper 모델 로딩 완료")

def _watch_settings():
    global _whisper_model, _current_model_size
    while True:
        time.sleep(3)
        try:
            size = _load_app_settings().get("whisper_model", "small")
            if size != _current_model_size and not _agent_busy.is_set():
                logging.info(f"모델 변경 감지: {_current_model_size} → {size}")
                new_model = WhisperModel(size, device="cpu", compute_type="int8")
                with _whisper_lock:
                    _whisper_model = new_model
                    _current_model_size = size
                logging.info(f"모델 교체 완료: {size}")
        except Exception as e:
            logging.warning(f"설정 감시 오류: {e}")

threading.Thread(target=_watch_settings, daemon=True).start()

def transcribe(audio):
    wav_bytes = audio.get_wav_data()
    with _whisper_lock:
        model = _whisper_model
    segments, _ = model.transcribe(
        io.BytesIO(wav_bytes), language="ko", beam_size=5, vad_filter=True,
        initial_prompt="자비스, 안녕하세요. 한국어로 말씀해 주세요."
    )
    return "".join(seg.text for seg in segments).strip()

def _listen_raw(timeout, phrase_time_limit, pause_threshold=1.5):
    r = sr.Recognizer()
    r.pause_threshold = pause_threshold
    r.non_speaking_duration = 0.6
    try:
        with sr.Microphone(device_index=MIC_INDEX) as source:
            r.adjust_for_ambient_noise(source, duration=0.3)
            try:
                audio = r.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            except sr.WaitTimeoutError:
                return None
    except Exception as e:
        logging.warning(f"마이크 오픈 실패: {e}")
        time.sleep(1)
        return None
    try:
        text = transcribe(audio)
        if not text or len(text) < 2:
            return None
        return text
    except Exception as e:
        logging.warning(f"STT 실패: {e}")
        return None

def listen_for_wake():
    """웨이크워드 감지 전용 — 짧게 듣고 텍스트만 반환, UI 상태 변경 없음"""
    return _listen_raw(timeout=3, phrase_time_limit=4, pause_threshold=0.8)

def listen():
    """명령어 수신 — 길게 듣고 로그 출력"""
    text = _listen_raw(timeout=5, phrase_time_limit=20, pause_threshold=1.5)
    if text:
        logging.info(f"listen: {text[:40]!r}")
        print(f"나: {text}")
    return text

# 웹 도구
def search_web(query, max_results=5):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results, region="kr-ko"))
        logging.info(f"search_web: {len(results)}개 결과")
        return results
    except Exception as e:
        logging.warning(f"search_web 실패: {e}")
        return []

def fetch_page(url, max_chars=3000):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:max_chars]
    except Exception as e:
        logging.warning(f"fetch_page 실패: {e}")
        return ""

APP_ALIASES = {
    "롤": "league of legends",
    "lol": "league of legends",
    "배그": "battlegrounds",
    "옵치": "overwatch",
    "오버워치": "overwatch",
    "스팀": "steam",
    "디코": "discord",
    "카톡": "kakaotalk",
    "유튜브": "youtube",
    "크롬": "chrome",
    "노트패드": "notepad",
}

def find_app(query):
    """설치된 앱을 이름으로 검색해서 경로 반환"""
    query = query.lower()
    query = APP_ALIASES.get(query, query)
    q_nospace = query.replace(" ", "").replace("-", "").replace("_", "")
    if platform.system() == "Windows":
        search_dirs = [
            os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
            os.path.expandvars(r"%AppData%\Microsoft\Windows\Start Menu\Programs"),
        ]
        candidates = []
        for d in search_dirs:
            if not os.path.exists(d):
                continue
            for root, _, files in os.walk(d):
                for f in files:
                    if not f.lower().endswith(".lnk"):
                        continue
                    fname = f[:-4].lower()
                    f_nospace = fname.replace(" ", "").replace("-", "").replace("_", "")
                    match = (
                        query in fname or fname in query or
                        q_nospace in f_nospace or f_nospace in q_nospace or
                        any(w in fname for w in query.split() if len(w) > 1)
                    )
                    if match:
                        candidates.append((len(fname), os.path.join(root, f)))
        if candidates:
            candidates.sort()
            path = candidates[0][1]
            logging.info(f"find_app: '{query}' → {path}")
            return path
    elif platform.system() == "Darwin":
        import glob as _glob
        for app in _glob.glob("/Applications/*.app"):
            fname = os.path.basename(app).replace(".app", "").lower()
            if query in fname or fname in query:
                logging.info(f"find_app: '{query}' → {app}")
                return app
    return None

def run_applescript(script):
    if platform.system() != "Darwin":
        return "AppleScript는 macOS에서만 실행할 수 있어요."
    # 셸 명령 실행은 막는다 (음성 오인식으로 임의 명령이 실행되는 것 방지)
    if "do shell script" in script.lower():
        return "보안상 do shell script는 실행할 수 없어요."
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15,
        )
    except subprocess.TimeoutExpired:
        return "AppleScript 실행 시간이 초과됐어요."
    logging.info(f"run_applescript: rc={result.returncode} {script[:80]!r}")
    if result.returncode != 0:
        return f"AppleScript 오류: {result.stderr.strip()[:300]}"
    return result.stdout.strip() or "실행 완료"

# 도구 실행
def call_tool(name, args):
    if name == "open_app":
        app_name = args.get("name", "").lower().strip()
        set_state("working")
        cmd = APPS.get(app_name)
        if not cmd:
            path = find_app(app_name)
            if path:
                if platform.system() == "Windows":
                    os.startfile(path)
                else:
                    subprocess.run(["open", path])
                time.sleep(0.5)
                return f"{app_name}을(를) 열었습니다."
            if platform.system() == "Windows":
                cmd = f"start {app_name}"
            else:
                cmd = f"open -a \"{app_name}\""
        result = subprocess.run(cmd, shell=True)
        time.sleep(0.5)
        if result.returncode == 0:
            return f"{app_name}을(를) 열었습니다."
        return f"{app_name}을(를) 찾을 수 없어요."

    elif name == "search_web":
        query = args.get("query", "")
        set_state("working")
        results = search_web(query)
        if not results:
            return "검색 결과가 없습니다."
        lines = [f"[검색 결과: {query}]"]
        for r in results[:4]:
            lines.append(f"- {r.get('title', '')}: {r.get('body', '')[:200]}")
        return "\n".join(lines)

    elif name == "fetch_page":
        url = args.get("url", "")
        set_state("working")
        return fetch_page(url) or "페이지를 가져올 수 없습니다."

    elif name == "run_applescript":
        script = args.get("script", "")
        set_state("working")
        return run_applescript(script)

    return f"알 수 없는 도구: {name}"

_agent_busy = threading.Event()

# Claude CLI 호출
def _flatten(text):
    # claude.cmd는 배치 파일이라 cmd.exe를 거쳐 실행되는데, 인자에 개행이 있으면
    # 그 뒤의 옵션이 통째로 유실된다 (예: --output-format json이 무시됨).
    return " ".join(text.split())

def call_claude(prompt_text):
    try:
        result = subprocess.run(
            [
                CLAUDE_CLI, "-p", _flatten(prompt_text),
                "--append-system-prompt", _flatten(SYSTEM_PROMPT),
                "--tools", "",
                "--output-format", "json",
                "--no-session-persistence",
                "--json-schema", CLAUDE_JSON_SCHEMA,
            ],
            capture_output=True, text=True, encoding="utf-8",
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
        data = json.loads(result.stdout)
    except Exception as e:
        logging.warning(f"call_claude 실패: {e}")
        return None, None

    if data.get("is_error"):
        logging.warning(f"call_claude 오류: {data.get('result')}")
        return None, None

    out = data.get("structured_output") or {}
    return out.get("reply"), out.get("tool_call")

# 에이전트 루프
def run_agent(user_input):
    _agent_busy.set()
    t0 = time.time()
    logging.info(f"run_agent: {user_input[:40]!r}")
    set_state("thinking")

    recent = conversation_history[-MAX_HISTORY:]
    context_lines = [
        f"{'사용자' if m['role'] == 'user' else '자비스'}: {m['content']}"
        for m in recent
    ]
    context_lines.append(f"사용자: {user_input}")

    final_reply = "죄송해요, 응답 처리 중 오류가 발생했어요."

    last_result = None
    for step in range(5):
        reply, tool_call = call_claude("\n".join(context_lines))

        if reply is None and tool_call is None:
            break

        if tool_call:
            tool_name = tool_call.get("name", "")
            tool_args = tool_call.get("args", {})
            logging.info(f"tool_call[{step}]: {tool_name}({tool_args})")
            result = call_tool(tool_name, tool_args)
            context_lines.append(f"[도구 결과 - {tool_name}]: {result}")
            last_result = result
            continue

        final_reply = reply or final_reply
        break
    else:
        # 도구 호출만 하다 횟수를 다 쓰면 오류 문구 대신 마지막 도구 결과를 말한다
        if last_result and len(last_result) < 200:
            final_reply = last_result

    try:
        conversation_history.append({"role": "user", "content": user_input})
        conversation_history.append({"role": "assistant", "content": final_reply})
        save_history(conversation_history)
        logging.info(f"run_agent total: {time.time()-t0:.2f}s")
        speak(final_reply)
    finally:
        _agent_busy.clear()
        set_state("standby")

# 유틸
def is_wake_word(text):
    return any(w in text for w in WAKE_WORDS)

def wants_to_exit(text):
    return any(w in text for w in EXIT_WORDS)

def poll_text_command():
    try:
        r = requests.get("http://127.0.0.1:8000/poll", timeout=1)
        return r.json().get("command")
    except:
        return None

def handle_command(user_input, source='voice'):
    if _agent_busy.is_set():
        return
    print(f"[UI 명령] {user_input} (source={source})")
    if source != 'ui':
        send_chat("user", user_input)
    thread = threading.Thread(target=run_agent, args=(user_input,))
    thread.daemon = True
    thread.start()

# main
set_state("standby")
print("자비스 대기 중...")

while True:
    if _agent_busy.is_set():
        time.sleep(0.1)
        continue

    set_state("standby")

    # UI 텍스트 명령 우선 처리
    text_cmd = poll_text_command()
    if text_cmd:
        handle_command(text_cmd, source='ui')
        continue

    # 웨이크워드만 조용히 감지 (UI는 standby 유지)
    wake_text = listen_for_wake()
    if not wake_text:
        continue

    if wants_to_exit(wake_text):
        speak("종료할게요. 안녕히 계세요!")
        time.sleep(3)
        break

    if not is_wake_word(wake_text):
        continue  # 웨이크워드 아니면 무시

    # 웨이크워드 감지 → listening 상태로 전환
    speak("네, 말씀하세요!")
    set_state("listening")
    user_input = listen()
    if not user_input:
        continue

    handle_command(user_input)
import os
import platform
import json
import time
import threading
import logging
import subprocess
import asyncio
import tempfile
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
import speech_recognition as sr
import pyttsx3
import edge_tts

# 설정
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_URL      = f"{OLLAMA_BASE_URL}/api/chat"
OLLAMA_MODEL    = "qwen3:4b"
SERVER_URL      = "http://127.0.0.1:8000/event"

HISTORY_FILE = "conversation_history.json"
MAX_HISTORY  = 6

WAKE_WORDS = ["자비스", "제이비스", "재비스"]
EXIT_WORDS = ["종료", "쉬어", "그만", "꺼져", "끝내", "닫아", "꺼"]

SYSTEM_PROMPT = """\
너는 자비스라는 AI 어시스턴트야. 간결하고 자연스럽게 한국어로 대답해줘.
도구 사용 규칙:
- 사용자가 앱을 열어달라고 하면 무조건 open_app 도구를 호출해. 앱 이름을 모르더라도 그냥 시도해.
- 최신 정보나 모르는 사실이 필요하면 search_web 도구를 호출해.
- 도구 결과를 받은 후 자연스럽게 한국어로 답변해줘."""

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

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "PC에서 앱을 실행합니다. 사용자가 앱을 열어달라고 요청할 때 사용하세요.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "실행할 앱 이름. 예: chrome, notepad, explorer, calculator, vscode, 또는 사용자가 요청한 앱 이름"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "웹에서 최신 정보를 검색합니다. 모르는 정보, 최신 뉴스, 날씨, 주가, 실시간 정보가 필요할 때 사용하세요.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "검색어"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_page",
            "description": "URL의 웹 페이지 내용을 가져옵니다. search_web으로 URL을 얻은 후 상세 내용이 필요할 때 사용하세요.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "가져올 웹 페이지 URL"
                    }
                },
                "required": ["url"]
            }
        }
    }
]

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

async def _tts_async(text, path):
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(path)


def speak(text):
    print(f"자비스: {text}")
    set_state("speaking")
    send_chat("jarvis", text)

    if platform.system() == "Darwin":
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()
        try:
            asyncio.run(_tts_async(text, tmp.name))
            subprocess.run(["afplay", tmp.name], check=True)
            time.sleep(0.3)
        except Exception as e:
            logging.warning(f"edge-tts 실패, pyttsx3 폴백: {e}")
            _speak_pyttsx3(text)
        finally:
            try:
                os.remove(tmp.name)
            except Exception:
                pass
    else:
        try:
            _speak_pyttsx3(text)
        except Exception as e:
            logging.warning(f"speak 실패: {e}")

    set_state("standby")

# STT
def listen():
    r = sr.Recognizer()
    try:
        with sr.Microphone() as source:
            r.adjust_for_ambient_noise(source)
            try:
                logging.info("listen: start")
                t0 = time.time()
                audio = r.listen(source, timeout=5)
                logging.info(f"listen: audio captured {time.time()-t0:.2f}s")
            except sr.WaitTimeoutError:
                return None
    except Exception as e:
        logging.warning(f"마이크 오픈 실패: {e}")
        time.sleep(1)
        return None
    try:
        t_rec0 = time.time()
        text = r.recognize_google(audio, language="ko-KR")
        logging.info(f"listen: recognize {time.time()-t_rec0:.2f}s -> {text[:40]!r}")
        print(f"나: {text}")
        return text
    except sr.UnknownValueError:
        return None
    except sr.RequestError:
        speak("인터넷 연결이 불안정합니다.")
        return None

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

# 도구 실행
def call_tool(name, args):
    if name == "open_app":
        app_name = args.get("name", "").lower().strip()
        set_state("working")
        cmd = APPS.get(app_name)
        if not cmd:
            path = find_app(app_name)
            if path:
                os.startfile(path)
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

    return f"알 수 없는 도구: {name}"

_agent_busy = threading.Event()

# 에이전트 루프
def run_agent(user_input):
    _agent_busy.set()
    t0 = time.time()
    logging.info(f"run_agent: {user_input[:40]!r}")
    set_state("thinking")
    send_chat("user", user_input)

    recent = conversation_history[-MAX_HISTORY:]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in recent:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": user_input})

    final_reply = "죄송해요, 응답 처리 중 오류가 발생했어요."

    for step in range(5):
        try:
            resp = requests.post(OLLAMA_URL, json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "tools": TOOLS,
                "stream": False,
            }, timeout=(5, 120))
        except Exception as e:
            logging.warning(f"run_agent 요청 실패: {e}")
            break

        data = resp.json()
        if "message" not in data:
            logging.warning(f"run_agent 응답 오류: {data}")
            break

        msg = data["message"]
        content = msg.get("content", "").strip()
        if "</think>" in content:
            content = content[content.rfind("</think>") + 8:].strip()

        tool_calls = msg.get("tool_calls", [])

        if not tool_calls:
            final_reply = content or final_reply
            break

        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            tool_args = fn.get("arguments", {})
            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except Exception:
                    tool_args = {}
            logging.info(f"tool_call[{step}]: {tool_name}({tool_args})")
            result = call_tool(tool_name, tool_args)
            messages.append({"role": "tool", "content": result, "name": tool_name})

    try:
        conversation_history.append({"role": "user", "content": user_input})
        conversation_history.append({"role": "assistant", "content": final_reply})
        save_history(conversation_history)
        logging.info(f"run_agent total: {time.time()-t0:.2f}s")
        speak(final_reply)
    finally:
        _agent_busy.clear()
        set_state("standby")

# Ollama 준비 대기
def wait_for_ollama_ready(timeout=180, interval=3):
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{OLLAMA_BASE_URL}/api/version", timeout=5)
            if resp.status_code == 200:
                logging.info("Ollama API ready")
                return True
        except requests.RequestException:
            pass
        time.sleep(interval)
    return False

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

def _warmup_model():
    if not wait_for_ollama_ready(timeout=120):
        logging.info("warmup: Ollama 준비 안 됨")
        return
    try:
        t0 = time.time()
        payload = {"model": OLLAMA_MODEL, "messages": [{"role": "user", "content": "안녕"}], "stream": False}
        r = requests.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=120)
        if r.status_code == 200:
            logging.info(f"warmup 완료 {time.time()-t0:.2f}s")
    except Exception as e:
        logging.info(f"warmup 실패: {e}")

threading.Thread(target=_warmup_model, daemon=True).start()

while True:
    if _agent_busy.is_set():
        time.sleep(0.1)
        continue

    set_state("standby")

    text_cmd = poll_text_command()
    if text_cmd:
        handle_command(text_cmd, source='ui')
        continue

    set_state("listening")
    user_input = listen()

    if not user_input:
        continue

    if wants_to_exit(user_input):
        speak("종료할게요. 안녕히 계세요!")
        time.sleep(3)
        break

    if is_wake_word(user_input.strip()):
        speak("네, 말씀하세요!")
        set_state("listening")
        user_input = listen()
        if not user_input:
            continue

    handle_command(user_input)

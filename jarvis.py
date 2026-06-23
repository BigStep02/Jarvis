import os
import platform
import json
import time
import threading
import logging
import subprocess
import webbrowser
import urllib.parse
import requests
import speech_recognition as sr
import pyttsx3

# 설정
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_URL      = f"{OLLAMA_BASE_URL}/api/chat"
OLLAMA_MODEL    = "qwen3:8b"
SERVER_URL      = "http://127.0.0.1:8000/event"

HISTORY_FILE = "conversation_history.json"
MAX_HISTORY  = 6

WAKE_WORDS = ["자비스", "제이비스", "재비스"]
EXIT_WORDS = ["종료", "쉬어", "그만", "꺼져", "끝내", "닫아", "꺼"]

SYSTEM_PROMPT = "너는 자비스라는 AI 어시스턴트야. 간결하고 자연스럽게 한국어로 대답해줘."

INTENT_SYSTEM_PROMPT = """\
/no_think
사용자 발화의 의도를 파악해서 아래 형식 중 하나로 JSON만 출력해. 다른 텍스트는 절대 출력하지 마.

앱 실행: {"type": "open_app", "name": "chrome|notepad|explorer|calculator|vscode"}
웹 검색: {"type": "search", "query": "검색어"}
일반 대화: {"type": "chat"}

앱 이름 규칙:
- 크롬, 브라우저, 구글크롬 → chrome
- 메모장, 텍스트편집기, textedit → notepad
- 탐색기, 파일탐색기, finder → explorer
- 계산기 → calculator
- vscode, 코드에디터, 비주얼스튜디오 → vscode"""

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
            "chrome":     "open -a \"Google Chrome\"",
            "notepad":    "open -a TextEdit",
            "explorer":   "open .",
            "calculator": "open -a Calculator",
            "vscode":     "code .",
        }

APPS = get_app_commands()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

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
def speak(text):
    print(f"자비스: {text}")
    set_state("speaking")
    send_chat("jarvis", text)
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
    set_state("standby")

# STT
def listen():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        r.adjust_for_ambient_noise(source)
        try:
            logging.info("listen: start")
            t0 = time.time()
            audio = r.listen(source, timeout=5)
            logging.info(f"listen: audio captured {time.time()-t0:.2f}s")
        except sr.WaitTimeoutError:
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

# 키워드 기반 의도 감지 (fallback)
def detect_action_keyword(text):
    t = text.lower()
    app_map = {
        ("크롬", "chrome", "브라우저"):              "chrome",
        ("메모장", "notepad", "textedit"):           "notepad",
        ("탐색기", "explorer", "파일탐색기", "finder"): "explorer",
        ("계산기", "calculator"):                    "calculator",
        ("vscode", "비에스코드", "코드에디터"):        "vscode",
    }
    for keywords, name in app_map.items():
        if any(k in t for k in keywords):
            if any(w in t for w in ["열어", "켜", "실행", "시작", "열기", "open"]):
                return {"type": "open_app", "name": name}
    if any(w in t for w in ["검색해", "찾아줘", "찾아봐", "구글에서"]):
        query = text
        for w in ["검색해줘", "검색해", "찾아줘", "찾아봐", "자비스"]:
            query = query.replace(w, "").strip()
        if query:
            return {"type": "search", "query": query}
    return None

# 사용자 발화 의도 감지 (LLM 기반, 실패 시 키워드 fallback)
def detect_action(text):
    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "stream": False,
        }, timeout=(2, 3))
        data = resp.json()
        if "error" in data:
            raise ValueError(data["error"])
        if "message" in data:
            content = data["message"]["content"].strip()
        elif "response" in data:
            content = data["response"].strip()
        else:
            raise ValueError(f"알 수 없는 응답 형식: {list(data.keys())}")

        if "</think>" in content:
            content = content[content.rfind("</think>") + 8:].strip()

        # JSON 코드블록 제거
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        action = json.loads(content)
        if action.get("type") == "chat":
            return None
        return action
    except Exception as e:
        try:
            logging.warning(f"detect_action LLM 실패 ({e}), 응답: {resp.json()}")
        except Exception:
            logging.warning(f"detect_action LLM 실패 ({e})")
        return detect_action_keyword(text)

# 작업 실행
def execute_action(action):
    if not action:
        return

    action_type = action.get("type")

    if action_type == "open_app":
        name = action.get("name", "").lower()
        cmd = APPS.get(name)
        if cmd:
            set_state("working")
            subprocess.Popen(cmd, shell=True)
            time.sleep(1.5)

    elif action_type == "search":
        query = action.get("query", "")
        if query:
            set_state("working")
            url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
            webbrowser.open(url)
            time.sleep(1.5)

# Ollama
def ask_ollama(user_input):
    recent = conversation_history[-MAX_HISTORY:]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in recent:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_input})

    response = requests.post(OLLAMA_URL, json={
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
    }, timeout=(5, 900))
    data = response.json()
    if "message" not in data:
        print(f"[Ollama 응답 오류] {data}")
        return "죄송해요, 응답 처리 중 오류가 발생했어요."
    content = data["message"]["content"].strip()

    if "</think>" in content:
        content = content[content.rfind("</think>") + 8:].strip()

    return content

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


def ask_ollama_safe(user_input):
    try:
        return ask_ollama(user_input)
    except requests.exceptions.ReadTimeout:
        logging.warning("Ollama request timed out; waiting for readiness and retrying")
        if wait_for_ollama_ready(timeout=120):
            try:
                return ask_ollama(user_input)
            except Exception as e:
                print(f"[Ollama 재시도 실패] {e}")
        return "죄송해요, AI 서버에 연결할 수 없어요. Ollama가 실행 중인지 확인해주세요."
    except Exception as e:
        print(f"[Ollama 연결 실패] {e}")
        return "죄송해요, AI 서버에 연결할 수 없어요. Ollama가 실행 중인지 확인해주세요."


def ask_ollama_stream(user_input, chunk_callback=None):
    """Try streaming response from Ollama. If chunk_callback provided, it's called with partial text chunks."""
    recent = conversation_history[-MAX_HISTORY:]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in recent:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_input})

    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": True,
        }, stream=True, timeout=(5, 900))
    except Exception as e:
        raise

    content = ""
    # Try to read streamed lines; fallback if not streaming
    try:
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                # try parse JSON if Ollama streams JSON objects
                j = json.loads(line)
                # extract possible text fields
                if isinstance(j, dict):
                    if "message" in j and isinstance(j["message"], dict):
                        part = j["message"].get("content", "")
                    else:
                        part = j.get("content", "") or j.get("text", "")
                else:
                    part = str(j)
            except Exception:
                part = line

            if part:
                content += part
                if chunk_callback:
                    chunk_callback(part)
        return content.strip()
    except Exception:
        # If streaming iteration fails, try non-stream path
        data = resp.json()
        if "message" in data:
            return data["message"].get("content", "").strip()
        return ""


def handle_ai_query(user_input):
    total_t0 = time.time()
    logging.info(f"handle_ai_query start: user={user_input[:40]!r}")
    set_state("thinking")
    send_chat("user", user_input)

    partial_buffer = []

    def on_chunk(part):
        # buffer small chunks and speak them
        partial_buffer.append(part)
        # if buffer length exceeds threshold, speak joined buffer
        joined = "".join(partial_buffer)
        if len(joined) > 60:
            try:
                speak(joined)
            except Exception:
                pass
            partial_buffer.clear()

    used_streaming = False
    try:
        # try streaming first
        t_model0 = time.time()
        reply = ask_ollama_stream(user_input, chunk_callback=on_chunk)
        logging.info(f"model_time (stream): {time.time()-t_model0:.2f}s")
        used_streaming = True
    except Exception as e:
        logging.info(f"streaming failed: {e}")
        t_model0 = time.time()
        reply = ask_ollama_safe(user_input)
        logging.info(f"model_time (sync): {time.time()-t_model0:.2f}s")

    # speak any remaining buffered text from streaming
    if partial_buffer:
        try:
            speak("".join(partial_buffer))
        except Exception:
            pass

    conversation_history.append({"role": "user", "content": user_input})
    conversation_history.append({"role": "assistant", "content": reply})
    save_history(conversation_history)

    # sync 경로일 때만 전체 reply를 TTS로 읽음 (streaming은 on_chunk에서 이미 처리)
    if not used_streaming and reply:
        try:
            t_speak0 = time.time()
            speak(reply)
            logging.info(f"tts_time: {time.time()-t_speak0:.2f}s")
        except Exception:
            pass

    logging.info(f"handle_ai_query total_time: {time.time()-total_t0:.2f}s")

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

ACTION_REPLIES = {
    "chrome":     "크롬을 열었습니다.",
    "notepad":    "메모장을 열었습니다.",
    "explorer":   "파일 탐색기를 열었습니다.",
    "calculator": "계산기를 열었습니다.",
    "vscode":     "VS Code를 열었습니다.",
}

def handle_command(user_input, source='voice'):
    print(f"[UI 명령] {user_input} (source={source})")
    # If the command came from the web UI (via websocket), main.py already
    # broadcasted the user message. Avoid sending it again to prevent duplicates.
    if source != 'ui':
        send_chat("user", user_input)

    action = detect_action(user_input)
    if action:
        execute_action(action)
        if action["type"] == "open_app":
            reply = ACTION_REPLIES.get(action["name"], "앱을 열었습니다.")
        else:
            reply = f"{action.get('query', '')} 검색을 시작합니다."
        conversation_history.append({"role": "user", "content": user_input})
        conversation_history.append({"role": "assistant", "content": reply})
        save_history(conversation_history)
        speak(reply)
        return

    # For AI queries, handle in background to avoid blocking main loop
    thread = threading.Thread(target=handle_ai_query, args=(user_input,))
    thread.daemon = True
    thread.start()

# main
set_state("standby")
print("자비스 대기 중...")

# Warmup model in background to avoid first-request cold start
def _warmup_model():
    # wait for Ollama HTTP API
    if not wait_for_ollama_ready(timeout=120):
        logging.info("warmup failed: Ollama API did not become ready")
        return

    # First, try a lightweight HTTP warmup (minimal prompt, no history)
    try:
        t0 = time.time()
        logging.info("warmup: sending lightweight HTTP prewarm request")
        payload = {"model": OLLAMA_MODEL, "messages": [{"role": "user", "content": "워밍업"}], "stream": False}
        try:
            r = requests.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=120)
            if r.status_code == 200:
                try:
                    data = r.json()
                    if isinstance(data, dict) and ("message" in data or "content" in data):
                        logging.info(f"warmup done (http) {time.time()-t0:.2f}s")
                        return
                except Exception:
                    pass
        except requests.exceptions.ReadTimeout:
            logging.info("warmup http request timed out, will try CLI spawn fallback")
        except Exception as e:
            logging.info(f"warmup http request failed: {e}")

    except Exception as e:
        logging.info(f"warmup http attempt error: {e}")

    # Fallback: try spawning a detached `ollama run` process to keep the model resident.
    # This helps with cold-starts on systems where the CLI starts the model process.
    try:
        devnull = subprocess.DEVNULL
        # send a short innocuous prompt so the CLI will load the model
        cmd = ["ollama", "run", OLLAMA_MODEL, "워밍업", "--nowordwrap"]
        subprocess.Popen(cmd, stdout=devnull, stderr=devnull, close_fds=True)
        logging.info("warmup: started ollama run subprocess (fallback)")
    except FileNotFoundError:
        logging.info("warmup fallback skipped: ollama CLI not found in PATH")
    except Exception as e:
        logging.info(f"warmup fallback failed: {e}")

threading.Thread(target=_warmup_model, daemon=True).start()

while True:
    set_state("standby")

    # UI 텍스트 입력 확인
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

    # 웨이크워드만 말한 경우 → 대기 응답 후 명령 대기
    if is_wake_word(user_input.strip()):
        speak("네, 말씀하세요!")
        set_state("listening")
        user_input = listen()
        if not user_input:
            continue

    handle_command(user_input)

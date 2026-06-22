import os
import json
import time
import subprocess
import webbrowser
import urllib.parse
import requests
import speech_recognition as sr
import pyttsx3

# 설정
OLLAMA_URL   = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "qwen3:8b"
SERVER_URL   = "http://127.0.0.1:8000/event"

HISTORY_FILE = "conversation_history.json"
MAX_HISTORY  = 20

WAKE_WORDS = ["자비스", "제이비스", "재비스"]
EXIT_WORDS = ["종료", "쉬어", "그만", "꺼져", "끝내", "닫아", "꺼"]

SYSTEM_PROMPT = "너는 자비스라는 AI 어시스턴트야. 간결하고 자연스럽게 한국어로 대답해줘."

APPS = {
    "chrome":     "start chrome",
    "크롬":        "start chrome",
    "notepad":    "start notepad",
    "메모장":      "start notepad",
    "explorer":   "start explorer",
    "탐색기":      "start explorer",
    "파일탐색기":   "start explorer",
    "calculator": "start calc",
    "계산기":      "start calc",
    "vscode":     "code .",
}

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
            audio = r.listen(source, timeout=5)
        except sr.WaitTimeoutError:
            return None
    try:
        text = r.recognize_google(audio, language="ko-KR")
        print(f"나: {text}")
        return text
    except sr.UnknownValueError:
        return None
    except sr.RequestError:
        speak("인터넷 연결이 불안정합니다.")
        return None

# 사용자 발화에서 직접 의도 감지
def detect_action(text):
    t = text.lower()

    # 앱 실행
    app_map = {
        ("크롬", "chrome"):                   "chrome",
        ("메모장", "notepad"):                 "notepad",
        ("탐색기", "explorer", "파일 탐색기"): "explorer",
        ("계산기", "calculator"):              "calculator",
        ("vscode", "비에스코드", "코드 에디터"): "vscode",
    }
    for keywords, name in app_map.items():
        if any(k in t for k in keywords):
            if any(w in t for w in ["열어", "켜", "실행", "시작", "열기"]):
                return {"type": "open_app", "name": name}

    # 웹 검색
    search_triggers = ["검색해", "찾아", "구글에서", "검색 해"]
    if any(w in t for w in search_triggers):
        query = text
        for w in ["검색해줘", "검색해", "찾아줘", "찾아봐", "구글에서 검색해줘", "자비스"]:
            query = query.replace(w, "").strip()
        if query:
            return {"type": "search", "query": query}

    return None

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
    }, timeout=60)
    data = response.json()
    if "message" not in data:
        print(f"[Ollama 응답 오류] {data}")
        return "죄송해요, 응답 처리 중 오류가 발생했어요."
    content = data["message"]["content"].strip()

    if "</think>" in content:
        content = content[content.rfind("</think>") + 8:].strip()

    return content

def ask_ollama_safe(user_input):
    try:
        return ask_ollama(user_input)
    except Exception as e:
        print(f"[Ollama 연결 실패] {e}")
        return "죄송해요, AI 서버에 연결할 수 없어요. Ollama가 실행 중인지 확인해주세요."

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

def handle_command(user_input):
    print(f"[UI 명령] {user_input}")
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

    set_state("thinking")
    reply = ask_ollama_safe(user_input)

    conversation_history.append({"role": "user", "content": user_input})
    conversation_history.append({"role": "assistant", "content": reply})
    save_history(conversation_history)

    speak(reply)

# main
set_state("standby")
print("자비스 대기 중...")

while True:
    set_state("standby")

    # UI 텍스트 입력 확인
    text_cmd = poll_text_command()
    if text_cmd:
        handle_command(text_cmd)
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

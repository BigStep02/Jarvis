import os
import json
import time
from dotenv import load_dotenv
import speech_recognition as sr
import pyttsx3
import google.generativeai as genai

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.0-flash")

HISTORY_FILE = "conversation_history.json"
MAX_HISTORY = 20  # 최근 20개 메시지만 컨텍스트로 사용

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[-200:], f, ensure_ascii=False, indent=2)

conversation_history = load_history()

def speak(text):
    print(f"자비스: {text}")
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

def listen():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print("듣는 중")
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

def ask_gemini(user_input):
    # 최근 대화 기록을 프롬프트에 포함
    recent = conversation_history[-MAX_HISTORY:]
    context = ""
    for msg in recent:
        role = "나" if msg["role"] == "user" else "자비스"
        context += f"{role}: {msg['content']}\n"

    prompt = f"너는 자비스라는 AI 어시스턴트야. 이전 대화를 참고해서 자연스럽게 대답해줘.\n\n{context}나: {user_input}\n자비스:"
    response = model.generate_content(prompt)
    return response.text.strip()

WAKE_WORDS = ["자비스", "제이비스", "재비스"]
EXIT_WORDS = ["종료", "쉬어", "그만", "꺼져", "끝내", "닫아", "꺼"]

def is_wake_word(text):
    return any(w in text for w in WAKE_WORDS)

def wants_to_exit(text):
    return any(w in text for w in EXIT_WORDS)

while True:
    wake = listen()
    if wake and is_wake_word(wake):
        speak("네, 말씀하세요!")
        time.sleep(0.5)
        user_input = listen()
        if user_input:
            if wants_to_exit(user_input):
                speak("종료할게요. 안녕히 계세요!")
                time.sleep(3)
                break

            answer = ask_gemini(user_input)

            # 대화 기록 저장
            conversation_history.append({"role": "user", "content": user_input})
            conversation_history.append({"role": "assistant", "content": answer})
            save_history(conversation_history)

            speak(answer)

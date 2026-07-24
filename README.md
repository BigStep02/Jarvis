# Jarvis — 음성 AI 어시스턴트

"자비스"라고 부르면 깨어나는 로컬 음성 AI 어시스턴트입니다.  
Claude CLI 기반으로 동작해 별도 API 비용이 없습니다.

---

## 주요 기능

- **웨이크워드 감지** — "자비스"라고 부를 때만 리스닝 모드로 전환 (항상 켜진 STT 없음)
- **로컬 STT** — faster-whisper 로컬 모델, 인터넷 없이 음성 인식
- **Claude CLI 연동** — Anthropic Claude를 LLM 두뇌로 활용
- **웹 검색 / 앱 실행** — DuckDuckGo 검색, macOS 앱 열기
- **실시간 파티클 UI** — 음성 주파수에 반응하는 2D 캔버스 애니메이션
- **시스템 통계 & 날씨** — CPU·RAM·디스크 실시간 표시, Open-Meteo 날씨
- **macOS 메뉴바 앱** — Whisper 모델 전환, 날씨 도시 설정 (재시작 없이 반영)
- **텍스트 입력 병행** — 브라우저 UI에서 타이핑으로도 명령 가능

---

## 아키텍처

```
[마이크] → faster-whisper (STT)
                │
        웨이크워드 감지
                │ "자비스"
        [명령어 수신]
                │
        Claude CLI (LLM)
                │
        edge-tts (TTS) → [스피커]
                │
        FastAPI WebSocket → [브라우저 UI]
```

| 컴포넌트 | 역할 |
|---|---|
| `jarvis.py` | 메인 에이전트 (STT·LLM·TTS 루프) |
| `main.py` | FastAPI 서버 (WebSocket·/stats·/weather) |
| `menubar.py` | macOS 메뉴바 앱 |
| `static/` | 브라우저 UI (HTML·CSS·JS) |
| `settings.json` | 런타임 설정 (Whisper 모델, 날씨 도시) |

---

## 요구사항

- macOS (Apple Silicon / Intel 모두 지원)
- Python 3.10 이상
- [Claude CLI](https://claude.ai/code) 설치 및 로그인 완료
- 마이크 접근 권한 (시스템 설정 → 개인 정보 보호 → 마이크)

---

## 설치

```bash
# 1. 저장소 클론
git clone https://github.com/BigStep02/Jarvis.git
cd Jarvis

# 2. 가상환경 생성 및 패키지 설치
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 실행

```bash
./start.sh
```

브라우저에서 `http://127.0.0.1:8000` 접속 후 "자비스"라고 부르거나 텍스트 입력으로 명령할 수 있습니다.

종료는 터미널에서 `Ctrl+C`.

---

## 메뉴바 설정

상단 메뉴바의 🤖 아이콘에서:

- **Whisper 모델 선택** — tiny / base / small / medium / large-v3 (재시작 없이 즉시 교체)
- **날씨 위치 변경** — 도시 이름 영문 입력 (예: `Busan`, `Seoul`)
- **대시보드 열기** — 브라우저 UI 포그라운드로 열기

---

## Whisper 모델 비교

| 모델 | 크기 | 정확도 | 속도 | 권장 용도 |
|---|---|---|---|---|
| tiny | ~75MB | ⭐⭐ | 가장 빠름 | 빠른 테스트 |
| base | ~145MB | ⭐⭐⭐ | 빠름 | 가벼운 사용 |
| **small** | ~465MB | ⭐⭐⭐⭐ | 보통 | **기본 권장** |
| medium | ~1.5GB | ⭐⭐⭐⭐⭐ | 느림 | 고정확도 필요 시 |
| large-v3 | ~3GB | ⭐⭐⭐⭐⭐⭐ | 매우 느림 | 최고 정확도 |

---

## 사용 가능한 명령 예시

| 명령 | 동작 |
|---|---|
| "자비스, 크롬 열어줘" | Google Chrome 실행 |
| "자비스, 오늘 날씨 어때?" | 웹 검색 후 답변 |
| "자비스, 블랙홀이 뭐야?" | 지식 질문 답변 |
| "자비스, 그만" | 프로그램 종료 |

---

## 설정 파일

`settings.json`은 메뉴바 앱이 자동으로 관리합니다. 직접 수정도 가능합니다.

```json
{
  "whisper_model": "small",
  "city": "Busan"
}
```

`city`를 비워두면 IP 기반 자동 감지를 사용합니다.

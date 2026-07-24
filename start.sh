#!/usr/bin/env bash
cd "$(dirname "$0")"

# venv 활성화
if [ -d "venv" ]; then
  source venv/bin/activate
else
  echo "venv가 없어요. 먼저 python3 -m venv venv && pip install -r requirements.txt 실행하세요."
  exit 1
fi

# 8000 포트 이미 사용 중이면 종료
EXISTING=$(lsof -ti :8000)
if [ -n "$EXISTING" ]; then
  echo "포트 8000 사용 중 (PID $EXISTING) → 종료 중..."
  kill $EXISTING
  sleep 0.5
fi

mkdir -p logs

# main.py 백그라운드 실행
echo "서버 시작 중..."
python main.py > logs/main.log 2>&1 &
MAIN_PID=$!
echo $MAIN_PID > run_main.pid
sleep 1

# 메뉴바 앱 백그라운드 실행
python menubar.py > logs/menubar.log 2>&1 &
MENUBAR_PID=$!

echo "자비스 시작!"
echo "브라우저: http://127.0.0.1:8000"
echo "메뉴바 아이콘(🤖)에서 모델 변경 가능"
echo "종료: Ctrl+C"
echo "──────────────────────────"

# jarvis.py 포그라운드 실행 (Ctrl+C 시 전부 종료)
trap "kill $MAIN_PID $MENUBAR_PID 2>/dev/null; echo '종료됨'" INT TERM
python jarvis.py
kill $MAIN_PID $MENUBAR_PID 2>/dev/null

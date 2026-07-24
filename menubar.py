import json
import os
import subprocess
import rumps

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

MODELS = ["tiny", "base", "small", "medium", "large-v3"]
MODEL_LABELS = {
    "tiny":     "Tiny     ⭐⭐       (최소)",
    "base":     "Base     ⭐⭐⭐     (균형)",
    "small":    "Small    ⭐⭐⭐⭐   (권장)",
    "medium":   "Medium   ⭐⭐⭐⭐⭐  (고정확도)",
    "large-v3": "Large    ⭐⭐⭐⭐⭐⭐ (최고)",
}
LABEL_TO_MODEL = {v: k for k, v in MODEL_LABELS.items()}

def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"whisper_model": "small"}

def save_settings(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class JarvisMenuBar(rumps.App):
    def __init__(self):
        super().__init__("🤖", quit_button=None)
        self.settings = load_settings()
        self._model_items = {}
        self._build_menu()

    def _build_menu(self):
        current = self.settings.get("whisper_model", "small")

        self._model_items = {}
        model_parent = rumps.MenuItem("Whisper 모델")
        for m in MODELS:
            label = MODEL_LABELS[m]
            item = rumps.MenuItem(label, callback=self._select_model)
            item.state = (m == current)
            self._model_items[m] = item
            model_parent.add(item)

        city_label = f"날씨 위치: {self.settings.get('city', 'Auto')}"
        self._city_item = rumps.MenuItem(city_label, callback=self._change_city)

        self.menu = [
            rumps.MenuItem("대시보드 열기", callback=self._open_dashboard),
            None,
            model_parent,
            self._city_item,
            None,
            rumps.MenuItem("종료", callback=rumps.quit_application),
        ]

    def _select_model(self, sender):
        selected = LABEL_TO_MODEL.get(sender.title)
        if not selected or selected == self.settings.get("whisper_model"):
            return

        self.settings["whisper_model"] = selected
        save_settings(self.settings)

        for m, item in self._model_items.items():
            item.state = (m == selected)

        rumps.notification("Jarvis", "모델 변경", f"{selected} 모델로 교체 중...", sound=False)

    def _change_city(self, sender):
        current = self.settings.get("city", "")
        response = rumps.Window(
            message="날씨에 표시할 도시 이름을 영문으로 입력하세요.\n(예: Busan, Seoul, Daegu)\n비워두면 IP 자동 감지",
            title="날씨 위치 변경",
            default_text=current,
            ok="저장",
            cancel="취소",
            dimensions=(260, 24),
        ).run()
        if response.clicked:
            city = response.text.strip()
            self.settings["city"] = city
            save_settings(self.settings)
            self._city_item.title = f"날씨 위치: {city or 'Auto'}"
            rumps.notification("Jarvis", "위치 변경", f"{'자동 감지' if not city else city}으로 설정됨", sound=False)

    def _open_dashboard(self, _):
        subprocess.run(["open", "http://127.0.0.1:8000"])


if __name__ == "__main__":
    JarvisMenuBar().run()

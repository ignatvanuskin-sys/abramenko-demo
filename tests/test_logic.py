"""Прогон сценария записи без внешних зависимостей."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.bot_logic import DialogState, reply

script = [
    "здравствуйте, хочу балаяж",
    "окрашены, был кератин",
    "в субботу утром",
    "Жамбыла",
    "Айгерим",
    "+7 707 123 45 67",
]

def main():
    st = DialogState()
    print("Бот: Здравствуйте! Abramenko Studio. Что вас интересует?")
    for u in script:
        print(f"Вы: {u}")
        print(f"Бот: {reply(st, u)}")
    assert st.step == "done", f"диалог не закрыт: {st.step}"
    assert st.phone, "телефон не собран"
    assert st.name, "имя не собрано"
    print("OK: запись собрана:", st.name, st.phone, "| филиал:", st.branch)

if __name__ == "__main__":
    main()

"""Консольное демо: python -m app.main_console"""
from dotenv import load_dotenv
from .bot_logic import DialogState, reply
from .llm_client import llm_available, llm_reply

load_dotenv()

def main():
    print("Abramenko Studio — демо. Команды: /reset, /exit")
    print("Бот: Здравствуйте! Abramenko Studio. Что вас интересует?")
    state = DialogState()
    history = []
    use_llm = llm_available()
    if use_llm:
        print("(LLM-режим включён)")
    else:
        print("(rule-based режим без ключа — работает сразу)")
    while True:
        try:
            user = input("Вы: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user:
            continue
        if user == "/exit":
            break
        if user == "/reset":
            state = DialogState()
            history = []
            print("Бот: Здравствуйте! Abramenko Studio. Что вас интересует?")
            continue
        if use_llm:
            history.append({"role": "user", "content": user})
            try:
                answer = llm_reply(history)
            except Exception as e:
                print(f"(LLM упал: {e}, переключаюсь на rule-based)")
                use_llm = False
                answer = reply(state, user)
            else:
                history.append({"role": "assistant", "content": answer})
                print(f"Бот: {answer}")
                continue
        print(f"Бот: {reply(state, user)}")

if __name__ == "__main__":
    main()

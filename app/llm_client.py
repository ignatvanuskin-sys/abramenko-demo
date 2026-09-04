"""LLM-режим поверх того же промпта. Без ключа проект работает в rule-based режиме."""
import os
from .prompt_loader import load_system_prompt

def llm_available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))

def llm_reply(messages: list[dict], temperature: float = 0.4) -> str:
    """Вызывается только если есть OPENAI_API_KEY. Требует pip install openai."""
    from openai import OpenAI
    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    system = load_system_prompt()
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, *messages],
        temperature=temperature,
        max_tokens=300,
    )
    return resp.choices[0].message.content.strip()

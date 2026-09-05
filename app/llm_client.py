"""LLM с provider abstraction и failover для WhatsApp-бота.

Поддерживает OpenAI-compatible провайдеры (Groq, OpenAI) через один интерфейс.
Без ключа — deterministic-only режим (safe fallback).

Env:
  LLM_PROVIDER=groq|openai   (default groq)
  LLM_MODEL=openai/gpt-oss-120b  (для groq) / gpt-4o-mini (для openai)
  LLM_API_KEY=...            (приоритет над OPENAI_API_KEY/GROQ_API_KEY)
  LLM_BASE_URL=https://api.groq.com/openai/v1
  LLM_TIMEOUT=5
  LLM_MAX_TOKENS=120
  LLM_FALLBACK_PROVIDER=openai (опционально)
  LLM_FALLBACK_MODEL=gpt-4o-mini
  LLM_FALLBACK_API_KEY=...
  LLM_FALLBACK_BASE_URL=https://api.openai.com/v1

Обратная совместимость: OPENAI_API_KEY/BASE_URL/MODEL работают как fallback.
"""
from __future__ import annotations

import logging
import os
import time
from typing import List, Dict, Optional

from .prompt_loader import load_system_prompt

logger = logging.getLogger("abramenko.llm")
_system_prompt_cache: Optional[str] = None
# Счётчики для /api/metrics (без PII)
LLM_STATS: Dict[str, int] = {"calls": 0, "failures": 0}

def _get_system_prompt() -> str:
    global _system_prompt_cache
    if _system_prompt_cache is None:
        try:
            _system_prompt_cache = load_system_prompt()
        except Exception:
            _system_prompt_cache = "Ты — администратор Abramenko Studio. Отвечай коротко, без выдумок."
    return _system_prompt_cache

def _get_config(prefix: str = "LLM") -> Optional[Dict[str, str]]:
    """Собирает конфиг провайдера. Возвращает None если ключа нет."""
    provider = (os.getenv(f"{prefix}_PROVIDER") or os.getenv("LLM_PROVIDER") or "").strip().lower()
    # legacy OPENAI_*
    api_key = (
        os.getenv(f"{prefix}_API_KEY")
        or os.getenv("LLM_API_KEY")
        or os.getenv("GROQ_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    ).strip()
    if not api_key:
        return None
    base_url = (
        os.getenv(f"{prefix}_BASE_URL")
        or os.getenv("LLM_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or ""
    ).strip()
    model = (
        os.getenv(f"{prefix}_MODEL")
        or os.getenv("LLM_MODEL")
        or os.getenv("OPENAI_MODEL")
        or ""
    ).strip()

    # дефолты по провайдеру
    if not provider:
        # авто-определение по base_url или ключу
        if "groq" in base_url.lower():
            provider = "groq"
        else:
            provider = "groq" if os.getenv("GROQ_API_KEY") else "openai"

    if not base_url:
        if provider == "groq":
            base_url = "https://api.groq.com/openai/v1"
        elif provider == "openai":
            base_url = "https://api.openai.com/v1"
        else:
            base_url = "https://api.openai.com/v1"

    if not model:
        if provider == "groq":
            model = "openai/gpt-oss-120b"
        else:
            model = "gpt-4o-mini"

    timeout = int(os.getenv(f"{prefix}_TIMEOUT") or os.getenv("LLM_TIMEOUT") or "5")
    max_tokens = int(os.getenv(f"{prefix}_MAX_TOKENS") or os.getenv("LLM_MAX_TOKENS") or "120")

    return {
        "provider": provider,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "timeout": str(timeout),
        "max_tokens": str(max_tokens),
    }

def _get_fallback_config() -> Optional[Dict[str, str]]:
    # явный fallback — только если LLM_FALLBACK_API_KEY задан
    if os.getenv("LLM_FALLBACK_API_KEY"):
        fallback = _get_config("LLM_FALLBACK")
        if fallback:
            return fallback
    # неявный: если primary groq, fallback openai если есть ключ
    primary = _get_config("LLM")
    if primary and primary["provider"] == "groq" and os.getenv("OPENAI_API_KEY"):
        return {
            "provider": "openai",
            "api_key": os.getenv("OPENAI_API_KEY", "").strip(),
            "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip(),
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
            "timeout": os.getenv("LLM_TIMEOUT", "5"),
            "max_tokens": os.getenv("LLM_MAX_TOKENS", "120"),
        }
    return None

def llm_available() -> bool:
    return _get_config() is not None

def _get_short_prompt() -> str:
    # сжатый промпт для Groq free tier (TPM 8k) — ~900 токенов вместо 5000
    return (
        "Ты — администратор Abramenko Studio, Петропавловск. Отвечай коротко, 1-2 строки, один вопрос за раз. Не выдумывай.\n"
        "Сеть: 2 точки. Букетова 61 (Abramenko Studio, Евразийский рынок 200м, 4.6 170, тел 3) — брови/лазер. "
        "Жамбыла 127 (Madame, Конституции 80м, 4.8 191, премия 2ГИС 2025, парковка 7) — свадебные/муж.маникюр.\n"
        "Слоган: Окрашивание и стрижки любой сложности. Оплата: карта/наличные/перевод. Wi-Fi есть.\n"
        "Цены: AirTouch/балаяж/dim-out/мелирование 25-80k, total blond 25-70k, коррекция 15-28k, один тон от 8k, выход из темного 35-130k, яркое 18-45k, коррекция сложных 30-50k, контуринг 18-28k, жен стрижка 4-7k (Madame от 5000), муж 2.5-4k (от 3500). Остальное — уточню у администратора.\n"
        "Правила: Сначала ответь, потом один вопрос. Не называть окна, не подтверждать запись, не обещать результат, не давать медсоветов. При срочности — взять имя/телефон. Если факта нет — \"Уточню у администратора\".\n"
    )

def _call_openai_compatible(cfg: Dict[str, str], messages: List[Dict[str, str]], temperature: float) -> str:
    from openai import OpenAI
    client = OpenAI(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        timeout=int(cfg["timeout"]),
        max_retries=0,
    )
    system = _get_system_prompt()
    # для Groq free tier TPM 8k — полный промпт 5k токенов превышает лимит, используем сжатый
    if cfg["provider"] == "groq" and len(system) > 4000:
        system = _get_short_prompt()
    resp = client.chat.completions.create(
        model=cfg["model"],
        messages=[{"role": "system", "content": system}, *messages],
        temperature=temperature,
        max_tokens=int(cfg["max_tokens"]),
        top_p=1,
    )
    content = resp.choices[0].message.content
    # лог полного сырого ответа ДО отправки в транспорт — для диагностики обрывов
    logger.info("llm raw response len=%d text=%r", len(content or ""), (content or "")[:2000])
    return (content or "").strip()

def llm_reply(messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
    """Основной вызов с failover. Никогда не должен вешать WhatsApp webhook."""
    # ограничим контекст: последние 4 сообщений максимум (скорость)
    msgs = messages[-4:] if len(messages) > 4 else messages
    # быстрый путь — primary
    cfg = _get_config()
    if not cfg:
        raise RuntimeError("LLM not configured")

    start = time.monotonic()
    last_err: Optional[Exception] = None

    for attempt, cur_cfg in enumerate([cfg, _get_fallback_config()]):  # primary, fallback
        if cur_cfg is None:
            continue
        # 429 retry один раз
        for retry in range(2):
            try:
                t0 = time.monotonic()
                result = _call_openai_compatible(cur_cfg, msgs, temperature)
                dt = (time.monotonic() - start) * 1000
                t_first = (time.monotonic() - t0) * 1000
                logger.info("llm ok provider=%s model=%s temp=%s total_ms=%.0f ttfb_ms=%.0f", cur_cfg["provider"], cur_cfg["model"], temperature, dt, t_first)
                if not result:
                    raise RuntimeError("empty llm response")
                LLM_STATS["calls"] += 1
                return result
            except Exception as e:
                last_err = e
                is_rate = "rate_limit" in str(e).lower() or "429" in str(e)
                dt = (time.monotonic() - start) * 1000
                logger.warning("llm fail provider=%s model=%s attempt=%s retry=%s ms=%.0f err=%s", cur_cfg["provider"], cur_cfg["model"], attempt, retry, dt, e)
                if is_rate and retry == 0:
                    time.sleep(4.5)
                    continue
                break
        # если это primary и есть fallback — пробуем дальше
        if attempt == 0 and _get_fallback_config() is not None:
            continue
        if last_err:
            LLM_STATS["failures"] += 1
            raise last_err

    # сюда не должны попасть
    raise RuntimeError(f"LLM all providers failed: {last_err}")

# Для тестов: сброс кэша
def _reset_cache():
    global _system_prompt_cache
    _system_prompt_cache = None

def classify_on_topic(user_text: str) -> bool:
    """Возвращает True если on_topic, False если off_topic. Использует LLM."""
    cfg = _get_config()
    if not cfg:
        raise RuntimeError("LLM not configured")
    # короткий промпт для классификации, без полного прайса
    system = (
        "Ты классификатор для салона красоты Abramenko Studio. "
        "on_topic=true если сообщение про: услуги/цены/волосы/ногти/брови/лазер/визаж/запись/филиалы/обучение beauty/вакансия beauty/модель beauty/мастеров/время. "
        "on_topic=false если про: вуз/университет/программирование/Python/английский/школу/математику/авто/игры/политику/погоду/новости/крипто/инвестиции/ремонт/путешествия и т.п. "
        "Если есть сомнение и хоть как-то можно связать с салоном — true. Иначе false. "
        "Ответ строго JSON: {\"on_topic\": true} или {\"on_topic\": false}"
    )
    from openai import OpenAI
    import json as _json
    client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"], timeout=int(cfg["timeout"]), max_retries=0)
    resp = client.chat.completions.create(
        model=cfg["model"],
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user_text}],
        temperature=0,
        max_tokens=10,
        top_p=1,
    )
    content = (resp.choices[0].message.content or "").strip().lower()
    # парсим JSON или ищем true/false
    try:
        data = _json.loads(content)
        if isinstance(data, dict) and "on_topic" in data:
            return bool(data["on_topic"])
    except Exception:
        pass
    if '"on_topic": true' in content or '"on_topic":true' in content or "true" in content:
        # простая эвристика
        if "false" in content and "true" not in content.split("false")[0]:
            return False
        return True
    if "false" in content:
        return False
    # по умолчанию считаем on_topic
    return True

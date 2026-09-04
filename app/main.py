"""Combined production entrypoint: Telegram polling + Web demo (FastAPI).

Запускает оба транспорта в одном процессе на Railway.
Если TELEGRAM_BOT_TOKEN отсутствует — web всё равно работает.
"""
import asyncio
import logging
import os

logger = logging.getLogger("abramenko.main")

async def main():
    # web — обязателен, telegram — опционален
    from app.web_api import app as web_app

    port = int(os.getenv("PORT", "8000"))
    import uvicorn

    config = uvicorn.Config(web_app, host="0.0.0.0", port=port, log_level="info", loop="asyncio")
    server = uvicorn.Server(config)

    # telegram — в отдельной задаче, чтобы падения не роняли web
    async def run_telegram():
        try:
            from app.main_telegram import main as telegram_main
            await telegram_main()
        except SystemExit as e:
            # токен не настроен — не роняем web, просто лог
            code = getattr(e, "code", 1)
            logger.warning("telegram disabled (exit %s) — web continues", code)
            # держим задачу живой, чтобы gather не завершился
            while True:
                await asyncio.sleep(3600)
        except Exception as e:
            logger.exception("telegram crashed: %s", e)
            while True:
                await asyncio.sleep(3600)

    # если токена нет, telegram_main всё равно сделает sleep+exit, но мы перехватим
    await asyncio.gather(
        server.serve(),
        run_telegram(),
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

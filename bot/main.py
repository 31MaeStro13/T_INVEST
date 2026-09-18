import asyncio
import logging
import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import load_bot_config
from bot.handlers import portfolio, start, token
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.services.api_client import BackendAPIClient

logger = logging.getLogger(__name__)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] #%(levelname)-8s %(filename)s:%(lineno)d - %(message)s",
    )
    logger.info("Запуск Telegram-бота T_INVEST...")

    config = load_bot_config()

    bot_session = None
    if config.telegram_proxy:
        logger.info("Подключение к Telegram API через прокси: %s", config.telegram_proxy)
        bot_session = AiohttpSession(proxy=config.telegram_proxy)

    bot = Bot(
        token=config.token,
        session=bot_session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Создаем единую aiohttp сессию и HTTP-клиент на весь жизненный цикл бота
    session = aiohttp.ClientSession()
    api_client = BackendAPIClient(base_url=config.backend_url, session=session)

    # Прокидываем api_client через workflow_data (dependency injection в хэндлеры)
    dp["api_client"] = api_client

    # Подключаем ThrottlingMiddleware (антиспам: не чаще 1 запроса в секунду)
    dp.message.middleware(ThrottlingMiddleware(rate_limit=1.0))

    # Регистрация роутеров
    dp.include_router(start.router)
    dp.include_router(token.router)
    dp.include_router(portfolio.router)

    try:
        # Пропускаем накопившиеся апдейты и запускаем polling
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        # Корректное закрытие сессий при остановке
        await session.close()
        await bot.session.close()
        logger.info("Бот и HTTP-сессии успешно остановлены.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную.")

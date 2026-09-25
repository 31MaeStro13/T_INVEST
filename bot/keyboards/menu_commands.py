import logging
from aiogram import Bot
from aiogram.types import BotCommandScopeDefault

logger = logging.getLogger(__name__)


async def delete_main_menu_commands(bot: Bot) -> None:
    """
    Полное удаление команд бота из стандартного скоупа (BotCommandScopeDefault),
    чтобы убрать всплывающую кнопку 'Menu' в интерфейсе Telegram.
    
    Поскольку всё взаимодействие в проекте реализовано через интерактивные
    кнопки портфеля и инлайн-клавиатуры, меню команд является избыточным.
    """
    try:
        await bot.delete_my_commands(scope=BotCommandScopeDefault())
        logger.info("Кнопка Menu и стандартные команды успешно удалены.")
    except Exception as e:
        logger.warning("Не удалось удалить команды меню: %s", e)

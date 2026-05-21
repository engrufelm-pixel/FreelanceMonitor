import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import ADMIN_ID, BOT_TOKEN
from database.models import init_db
from handlers.admin import router as admin_router
from handlers.tasks import router as tasks_router
from services.monitor import monitor_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    if not BOT_TOKEN or not ADMIN_ID:
        raise RuntimeError("BOT_TOKEN или ADMIN_ID не заданы в .env")

    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin_router)
    dp.include_router(tasks_router)

    @dp.startup()
    async def on_startup(bot: Bot) -> None:
        logger.info("Бот запущен. Admin ID: %d", ADMIN_ID)
        asyncio.create_task(monitor_loop(bot, ADMIN_ID))
        try:
            await bot.send_message(ADMIN_ID, "🟢 FreelanceMonitor запущен")
        except Exception as e:
            logger.warning("Не удалось приветствовать админа: %s", e)

    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    asyncio.run(main())

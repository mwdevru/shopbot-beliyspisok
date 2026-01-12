import asyncio
import logging

from yookassa import Configuration
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from shop_bot.data_manager import database
from shop_bot.bot.handlers import get_user_router
from shop_bot.bot.middlewares import BanMiddleware
from shop_bot.bot import handlers, support_handlers
from shop_bot.bot.support_handlers import get_support_router

logger = logging.getLogger(__name__)


class BotController:
    def __init__(self):
        self._loop = None
        self.shop_bot = None
        self.shop_dp = None
        self.shop_task = None
        self.shop_is_running = False
        self.support_bot = None
        self.support_dp = None
        self.support_task = None
        self.support_is_running = False

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        logger.info("BotController: Event loop has been set.")

    def get_bot_instance(self) -> Bot | None:
        return self.shop_bot

    async def _start_polling(self, bot, dp, name):
        logger.info(f"BotController: Polling task for '{name}' has been started.")
        try:
            await dp.start_polling(bot)
        except asyncio.CancelledError:
            logger.info(f"BotController: Polling task for '{name}' was cancelled.")
        except Exception as e:
            logger.error(f"BotController: An error occurred during polling for '{name}': {e}", exc_info=True)
        finally:
            logger.info(f"BotController: Polling for '{name}' has gracefully stopped.")
            if bot:
                await bot.close()
            if name == "ShopBot":
                self.shop_is_running = False
                self.shop_task = None
                self.shop_bot = None
                self.shop_dp = None
            elif name == "SupportBot":
                self.support_is_running = False
                self.support_task = None
                self.support_bot = None
                self.support_dp = None

    def start_shop_bot(self):
        if self.shop_is_running:
            return {"status": "error", "message": "Бот уже запущен."}

        if not self._loop or not self._loop.is_running():
            return {"status": "error", "message": "Критическая ошибка: цикл событий не установлен."}

        token = database.get_setting("telegram_bot_token")
        bot_username = database.get_setting("telegram_bot_username")
        admin_id = database.get_setting("admin_telegram_id")

        if not all([token, bot_username, admin_id]):
            return {
                "status": "error",
                "message": "Невозможно запустить: не все обязательные настройки Telegram заполнены."
            }

        try:
            self.shop_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            self.shop_dp = Dispatcher()
            self.shop_dp.update.middleware(BanMiddleware())
            self.shop_dp.include_router(get_user_router())

            self.shop_is_running = True

            yookassa_shop_id = database.get_setting("yookassa_shop_id")
            yookassa_secret_key = database.get_setting("yookassa_secret_key")
            yookassa_enabled = bool(yookassa_shop_id and yookassa_secret_key)

            if yookassa_enabled:
                Configuration.account_id = yookassa_shop_id
                Configuration.secret_key = yookassa_secret_key

            handlers.TELEGRAM_BOT_USERNAME = bot_username
            handlers.ADMIN_ID = admin_id

            self.shop_task = asyncio.run_coroutine_threadsafe(
                self._start_polling(self.shop_bot, self.shop_dp, "ShopBot"), self._loop
            )
            logger.info("BotController: Start command sent to event loop.")
            return {"status": "success", "message": "Команда на запуск бота отправлена."}

        except Exception as e:
            logger.error(f"Failed to start bot: {e}", exc_info=True)
            self.shop_bot = None
            self.shop_dp = None
            return {"status": "error", "message": f"Ошибка при запуске: {e}"}

    def start_support_bot(self):
        if self.support_is_running:
            return {"status": "error", "message": "Бот-Саппорт уже запущен."}

        token = database.get_setting("support_bot_token")
        group_id = database.get_setting("support_group_id")

        if not token or not group_id:
            return {"status": "error", "message": "Токен для Бота-Саппорта и Айди группы не указаны."}

        try:
            self.support_bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            self.support_dp = Dispatcher()

            support_handlers.SUPPORT_GROUP_ID = int(group_id)
            support_handlers.user_bot = self.shop_bot

            support_router = get_support_router()
            self.support_dp.include_router(support_router)

            self.support_is_running = True
            self.support_task = asyncio.run_coroutine_threadsafe(
                self._start_polling(self.support_bot, self.support_dp, "SupportBot"), self._loop
            )
            return {"status": "success", "message": "Команда на запуск бота отправлена."}
        except Exception as e:
            self.support_bot = None
            self.support_dp = None
            logger.error(f"Failed to start Support Bot: {e}", exc_info=True)
            return {"status": "error", "message": f"Error starting Support Bot: {e}"}

    def stop_shop_bot(self):
        if not self.shop_is_running:
            return {"status": "error", "message": "Бот не запущен."}

        if not self._loop or not self.shop_dp:
            return {"status": "error", "message": "Критическая ошибка: компоненты бота недоступны."}

        self.shop_is_running = False
        logger.info("BotController: Sending graceful stop signal...")
        asyncio.run_coroutine_threadsafe(self.shop_dp.stop_polling(), self._loop)

        return {"status": "success", "message": "Команда на остановку бота отправлена."}

    def stop_support_bot(self):
        if not self.support_is_running:
            return {"status": "error", "message": "Бот не запущен."}

        if not self._loop or not self.support_dp:
            return {"status": "error", "message": "Критическая ошибка: компоненты бота недоступны."}

        self.support_is_running = False
        logger.info("BotController: Sending graceful stop signal...")
        asyncio.run_coroutine_threadsafe(self.support_dp.stop_polling(), self._loop)

        return {"status": "success", "message": "Команда на остановку бота отправлена."}

    def get_status(self):
        return {
            "shop_bot_running": self.shop_is_running,
            "support_bot_running": self.support_is_running
        }

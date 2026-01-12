import logging
import json

from aiogram import Bot, Router, F, types
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode

from shop_bot.data_manager import database

logger = logging.getLogger(__name__)

SUPPORT_GROUP_ID = None


async def get_user_summary(user_id: int, username: str) -> str:
    keys = database.get_user_keys(user_id)
    latest_transaction = database.get_latest_transaction(user_id)

    summary_parts = [
        f"<b>Новый тикет от пользователя:</b> @{username} (ID: <code>{user_id}</code>)\n"
    ]

    if keys:
        summary_parts.append("<b>🔑 Активные ключи:</b>")
        for key in keys:
            expiry = key['expiry_date'].split(' ')[0]
            summary_parts.append(f"- <code>{key['key_email']}</code> (до {expiry} на хосте {key['host_name']})")
    else:
        summary_parts.append("<b>🔑 Активные ключи:</b> Нет")

    if latest_transaction:
        summary_parts.append("\n<b>💸 Последняя транзакция:</b>")
        metadata = json.loads(latest_transaction.get('metadata', '{}'))
        plan_name = metadata.get('plan_name', 'N/A')
        price = latest_transaction.get('amount_rub', 'N/A')
        date = latest_transaction.get('created_date', '').split(' ')[0]
        summary_parts.append(f"- {plan_name} за {price} RUB ({date})")
    else:
        summary_parts.append("\n<b>💸 Последняя транзакция:</b> Нет")

    return "\n".join(summary_parts)


def get_support_router() -> Router:
    support_router = Router()

    @support_router.message(CommandStart())
    async def handle_start(message: types.Message, bot: Bot):
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.full_name

        thread_id = database.get_support_thread_id(user_id)

        if not thread_id:
            if not SUPPORT_GROUP_ID:
                logger.error("Support bot: SUPPORT_GROUP_ID is not configured!")
                await message.answer("Извините, служба поддержки временно недоступна.")
                return

            try:
                thread_name = f"Тикет от @{username} ({user_id})"
                new_thread = await bot.create_forum_topic(chat_id=SUPPORT_GROUP_ID, name=thread_name)
                thread_id = new_thread.message_thread_id

                database.add_support_thread(user_id, thread_id)

                summary_text = await get_user_summary(user_id, username)
                await bot.send_message(
                    chat_id=SUPPORT_GROUP_ID,
                    message_thread_id=thread_id,
                    text=summary_text,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Created new support thread {thread_id} for user {user_id}")

            except Exception as e:
                logger.error(f"Failed to create support thread for user {user_id}: {e}", exc_info=True)
                await message.answer("Не удалось создать тикет в поддержке. Пожалуйста, попробуйте позже.")
                return

        await message.answer("Напишите ваш вопрос, и администратор скоро с вами свяжется.")

    @support_router.message(F.chat.type == "private")
    async def from_user_to_admin(message: types.Message, bot: Bot):
        user_id = message.from_user.id
        thread_id = database.get_support_thread_id(user_id)

        if thread_id and SUPPORT_GROUP_ID:
            await bot.copy_message(
                chat_id=SUPPORT_GROUP_ID,
                from_chat_id=user_id,
                message_id=message.message_id,
                message_thread_id=thread_id
            )
        else:
            await message.answer("Пожалуйста, сначала нажмите /start, чтобы создать тикет в поддержке.")

    @support_router.message(F.chat.id == SUPPORT_GROUP_ID, F.message_thread_id)
    async def from_admin_to_user(message: types.Message, bot: Bot):
        thread_id = message.message_thread_id
        user_id = database.get_user_id_by_thread(thread_id)

        if message.from_user.id == bot.id:
            return

        if user_id:
            try:
                await bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=SUPPORT_GROUP_ID,
                    message_id=message.message_id
                )
            except Exception as e:
                logger.error(f"Failed to send message from thread {thread_id} to user {user_id}: {e}")
                await message.reply("❌ Не удалось доставить сообщение этому пользователю.")

    return support_router

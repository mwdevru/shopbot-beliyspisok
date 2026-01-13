import logging
import json
import asyncio
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any

from aiogram import Bot, Router, F, types
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from shop_bot.data_manager import database

logger = logging.getLogger(__name__)

SUPPORT_GROUP_ID = None


class TicketStatus(Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING_USER = "waiting_user"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


STATUS_EMOJI = {
    TicketStatus.OPEN: "🆕",
    TicketStatus.IN_PROGRESS: "🔄",
    TicketStatus.WAITING_USER: "⏳",
    TicketStatus.RESOLVED: "✅",
    TicketStatus.CLOSED: "🔒"
}

PRIORITY_EMOJI = {
    TicketPriority.LOW: "🟢",
    TicketPriority.NORMAL: "🟡",
    TicketPriority.HIGH: "🟠",
    TicketPriority.URGENT: "🔴"
}


class SupportStates(StatesGroup):
    waiting_for_category = State()
    waiting_for_message = State()
    rating_feedback = State()


SUPPORT_CATEGORIES = {
    "payment": "💳 Проблемы с оплатой",
    "vpn": "🔑 Проблемы с VPN/ключами",
    "account": "👤 Вопросы по аккаунту",
    "refund": "💸 Возврат средств",
    "other": "❓ Другое"
}


def get_ticket_status(user_id: int) -> Optional[str]:
    return database.get_support_ticket_status(user_id)


def set_ticket_status(user_id: int, status: TicketStatus):
    database.update_support_ticket_status(user_id, status.value)


def get_ticket_priority(user_id: int) -> Optional[str]:
    return database.get_support_ticket_priority(user_id)


def set_ticket_priority(user_id: int, priority: TicketPriority):
    database.update_support_ticket_priority(user_id, priority.value)


async def get_user_summary(user_id: int, username: str, category: str = None) -> str:
    keys = database.get_user_keys(user_id)
    latest_transaction = database.get_latest_transaction(user_id)
    user_data = database.get_user(user_id)
    now = datetime.now()

    summary_parts = [
        f"{'─' * 30}",
        f"🎫 <b>НОВЫЙ ТИКЕТ</b>",
        f"{'─' * 30}",
        f"",
        f"👤 <b>Пользователь:</b> @{username}",
        f"🆔 <b>ID:</b> <code>{user_id}</code>",
    ]

    if category and category in SUPPORT_CATEGORIES:
        summary_parts.append(f"📂 <b>Категория:</b> {SUPPORT_CATEGORIES[category]}")

    if user_data:
        reg_date = user_data.get('registration_date', '')
        if reg_date:
            try:
                reg_dt = datetime.fromisoformat(reg_date.replace(' ', 'T'))
                days_since_reg = (now - reg_dt).days
                summary_parts.append(f"📅 <b>Зарегистрирован:</b> {reg_dt.strftime('%d.%m.%Y')} ({days_since_reg} дн.)")
            except:
                pass
        total_spent = user_data.get('total_spent', 0)
        if total_spent > 0:
            summary_parts.append(f"💰 <b>Всего потрачено:</b> {total_spent:.0f} RUB")

    summary_parts.append("")

    if keys:
        active_keys = []
        expired_keys = []
        for key in keys:
            try:
                expiry = datetime.fromisoformat(key['expiry_date'].replace(' ', 'T'))
                if expiry > now:
                    days_left = (expiry - now).days
                    active_keys.append((key, expiry, days_left))
                else:
                    expired_keys.append((key, expiry))
            except:
                pass

        if active_keys:
            summary_parts.append(f"🔑 <b>Активные ключи ({len(active_keys)}):</b>")
            for key, expiry, days_left in active_keys:
                status = "⚠️" if days_left <= 3 else "✅"
                summary_parts.append(f"  {status} до {expiry.strftime('%d.%m.%Y')} ({days_left} дн.)")
        else:
            summary_parts.append("🔑 <b>Активные ключи:</b> Нет")

        if expired_keys:
            summary_parts.append(f"❌ <b>Истёкшие ключи:</b> {len(expired_keys)}")
    else:
        summary_parts.append("🔑 <b>Ключи:</b> Нет")

    summary_parts.append("")

    if latest_transaction:
        try:
            metadata = json.loads(latest_transaction.get('metadata', '{}'))
            plan_name = metadata.get('plan_name', 'N/A')
            price = latest_transaction.get('amount_rub', 0)
            status = latest_transaction.get('status', 'N/A')
            date = latest_transaction.get('created_date', '').split(' ')[0]
            payment_method = latest_transaction.get('payment_method', 'N/A')

            status_emoji = "✅" if status == "paid" else "⏳" if status == "pending" else "❌"
            summary_parts.append(f"💸 <b>Последняя транзакция:</b>")
            summary_parts.append(f"  {status_emoji} {plan_name} — {price:.0f} RUB")
            summary_parts.append(f"  📅 {date} | 💳 {payment_method}")
        except:
            summary_parts.append("💸 <b>Последняя транзакция:</b> Ошибка данных")
    else:
        summary_parts.append("💸 <b>Транзакции:</b> Нет")

    summary_parts.extend([
        "",
        f"{'─' * 30}",
        f"⚡ <b>Быстрые команды:</b>",
        f"/close — закрыть тикет",
        f"/priority [low/normal/high/urgent]",
        f"/note [текст] — добавить заметку",
        f"{'─' * 30}"
    ])

    return "\n".join(summary_parts)


def create_category_keyboard() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for cat_id, cat_name in SUPPORT_CATEGORIES.items():
        builder.button(text=cat_name, callback_data=f"support_cat_{cat_id}")
    builder.adjust(1)
    return builder.as_markup()


def create_ticket_actions_keyboard(user_id: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Решено", callback_data=f"ticket_resolve_{user_id}")
    builder.button(text="🔒 Закрыть", callback_data=f"ticket_close_{user_id}")
    builder.button(text="⏳ Ожидание", callback_data=f"ticket_wait_{user_id}")
    builder.button(text="🔴 Срочно", callback_data=f"ticket_urgent_{user_id}")
    builder.adjust(2)
    return builder.as_markup()


def create_rating_keyboard() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐", callback_data="rate_1")
    builder.button(text="⭐⭐", callback_data="rate_2")
    builder.button(text="⭐⭐⭐", callback_data="rate_3")
    builder.button(text="⭐⭐⭐⭐", callback_data="rate_4")
    builder.button(text="⭐⭐⭐⭐⭐", callback_data="rate_5")
    builder.adjust(5)
    return builder.as_markup()


def create_back_keyboard() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Отмена", callback_data="support_cancel")
    return builder.as_markup()


def get_support_router() -> Router:
    support_router = Router()

    @support_router.message(CommandStart())
    async def handle_start(message: types.Message, bot: Bot, state: FSMContext):
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.full_name

        thread_id = database.get_support_thread_id(user_id)

        if thread_id:
            status = get_ticket_status(user_id)
            if status == TicketStatus.CLOSED.value:
                database.delete_support_thread(user_id)
                thread_id = None

        if thread_id:
            await message.answer(
                "📬 У вас уже есть открытый тикет.\n\n"
                "Просто напишите ваше сообщение, и оно будет отправлено в поддержку.\n\n"
                "Используйте /newticket чтобы создать новый тикет."
            )
            return

        await message.answer(
            "👋 <b>Добро пожаловать в службу поддержки!</b>\n\n"
            "Выберите категорию вашего обращения:",
            reply_markup=create_category_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await state.set_state(SupportStates.waiting_for_category)

    @support_router.message(Command("newticket"))
    async def new_ticket_handler(message: types.Message, bot: Bot, state: FSMContext):
        user_id = message.from_user.id

        old_thread_id = database.get_support_thread_id(user_id)
        if old_thread_id:
            database.delete_support_thread(user_id)
            if SUPPORT_GROUP_ID:
                try:
                    await bot.send_message(
                        chat_id=SUPPORT_GROUP_ID,
                        message_thread_id=old_thread_id,
                        text="🔄 Пользователь создал новый тикет. Этот тикет закрыт."
                    )
                except:
                    pass

        await message.answer(
            "🆕 <b>Создание нового тикета</b>\n\n"
            "Выберите категорию вашего обращения:",
            reply_markup=create_category_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await state.set_state(SupportStates.waiting_for_category)

    @support_router.callback_query(SupportStates.waiting_for_category, F.data.startswith("support_cat_"))
    async def category_selected(callback: types.CallbackQuery, bot: Bot, state: FSMContext):
        category = callback.data.replace("support_cat_", "")
        user_id = callback.from_user.id
        username = callback.from_user.username or callback.from_user.full_name

        await callback.answer()

        if not SUPPORT_GROUP_ID:
            logger.error("Support bot: SUPPORT_GROUP_ID is not configured!")
            await callback.message.edit_text("❌ Служба поддержки временно недоступна.")
            await state.clear()
            return

        try:
            cat_name = SUPPORT_CATEGORIES.get(category, "Другое")
            thread_name = f"[{cat_name.split()[0]}] @{username} ({user_id})"
            if len(thread_name) > 128:
                thread_name = thread_name[:125] + "..."

            new_thread = await bot.create_forum_topic(chat_id=SUPPORT_GROUP_ID, name=thread_name)
            thread_id = new_thread.message_thread_id

            database.add_support_thread(user_id, thread_id, category)
            set_ticket_status(user_id, TicketStatus.OPEN)

            if category in ["payment", "refund"]:
                set_ticket_priority(user_id, TicketPriority.HIGH)
            else:
                set_ticket_priority(user_id, TicketPriority.NORMAL)

            summary_text = await get_user_summary(user_id, username, category)
            await bot.send_message(
                chat_id=SUPPORT_GROUP_ID,
                message_thread_id=thread_id,
                text=summary_text,
                parse_mode=ParseMode.HTML,
                reply_markup=create_ticket_actions_keyboard(user_id)
            )

            logger.info(f"Created support thread {thread_id} for user {user_id}, category: {category}")

            await callback.message.edit_text(
                f"✅ <b>Тикет создан!</b>\n\n"
                f"📂 Категория: {cat_name}\n\n"
                f"Опишите вашу проблему подробно. Прикрепите скриншоты, если это поможет.",
                parse_mode=ParseMode.HTML
            )
            await state.clear()

        except Exception as e:
            logger.error(f"Failed to create support thread for user {user_id}: {e}", exc_info=True)
            await callback.message.edit_text(
                "❌ Не удалось создать тикет. Попробуйте позже или напишите напрямую администратору."
            )
            await state.clear()

    @support_router.callback_query(F.data == "support_cancel")
    async def cancel_support(callback: types.CallbackQuery, state: FSMContext):
        await callback.answer("Отменено")
        await callback.message.edit_text("❌ Создание тикета отменено.")
        await state.clear()

    @support_router.message(F.chat.type == "private", ~StateFilter(SupportStates.waiting_for_category))
    async def from_user_to_admin(message: types.Message, bot: Bot, state: FSMContext):
        user_id = message.from_user.id
        thread_id = database.get_support_thread_id(user_id)

        if not thread_id or not SUPPORT_GROUP_ID:
            await message.answer(
                "📝 Чтобы связаться с поддержкой, нажмите /start и выберите категорию обращения."
            )
            return

        status = get_ticket_status(user_id)
        if status == TicketStatus.CLOSED.value:
            await message.answer(
                "🔒 Ваш предыдущий тикет был закрыт.\n"
                "Используйте /newticket для создания нового обращения."
            )
            return

        try:
            if status == TicketStatus.WAITING_USER.value:
                set_ticket_status(user_id, TicketStatus.IN_PROGRESS)

            await bot.copy_message(
                chat_id=SUPPORT_GROUP_ID,
                from_chat_id=user_id,
                message_id=message.message_id,
                message_thread_id=thread_id
            )

            database.increment_ticket_messages(user_id)

        except TelegramBadRequest as e:
            if "thread not found" in str(e).lower():
                database.delete_support_thread(user_id)
                await message.answer(
                    "⚠️ Ваш тикет был закрыт.\n"
                    "Используйте /start для создания нового обращения."
                )
            else:
                logger.error(f"Failed to forward message from user {user_id}: {e}")
        except Exception as e:
            logger.error(f"Failed to forward message from user {user_id}: {e}")

    @support_router.message(F.chat.id == SUPPORT_GROUP_ID, F.message_thread_id, Command("close"))
    async def close_ticket_command(message: types.Message, bot: Bot):
        thread_id = message.message_thread_id
        user_id = database.get_user_id_by_thread(thread_id)

        if not user_id:
            await message.reply("❌ Пользователь не найден.")
            return

        set_ticket_status(user_id, TicketStatus.CLOSED)

        try:
            await bot.send_message(
                chat_id=user_id,
                text="🔒 <b>Ваш тикет был закрыт.</b>\n\n"
                     "Если у вас остались вопросы, создайте новое обращение командой /start\n\n"
                     "Пожалуйста, оцените качество поддержки:",
                parse_mode=ParseMode.HTML,
                reply_markup=create_rating_keyboard()
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id} about ticket closure: {e}")

        await message.reply("✅ Тикет закрыт. Пользователю отправлен запрос на оценку.")

        try:
            await bot.close_forum_topic(chat_id=SUPPORT_GROUP_ID, message_thread_id=thread_id)
        except:
            pass

    @support_router.message(F.chat.id == SUPPORT_GROUP_ID, F.message_thread_id, Command("priority"))
    async def set_priority_command(message: types.Message, bot: Bot):
        thread_id = message.message_thread_id
        user_id = database.get_user_id_by_thread(thread_id)

        if not user_id:
            await message.reply("❌ Пользователь не найден.")
            return

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply("Использование: /priority [low/normal/high/urgent]")
            return

        priority_str = args[1].lower()
        priority_map = {
            "low": TicketPriority.LOW,
            "normal": TicketPriority.NORMAL,
            "high": TicketPriority.HIGH,
            "urgent": TicketPriority.URGENT
        }

        if priority_str not in priority_map:
            await message.reply("❌ Неверный приоритет. Используйте: low, normal, high, urgent")
            return

        priority = priority_map[priority_str]
        set_ticket_priority(user_id, priority)
        await message.reply(f"{PRIORITY_EMOJI[priority]} Приоритет изменён на: {priority_str.upper()}")

    @support_router.message(F.chat.id == SUPPORT_GROUP_ID, F.message_thread_id, Command("note"))
    async def add_note_command(message: types.Message):
        thread_id = message.message_thread_id
        user_id = database.get_user_id_by_thread(thread_id)

        if not user_id:
            await message.reply("❌ Пользователь не найден.")
            return

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply("Использование: /note [текст заметки]")
            return

        note_text = args[1]
        database.add_ticket_note(user_id, note_text, message.from_user.username or "Admin")
        await message.reply(f"📝 Заметка добавлена:\n<i>{note_text}</i>", parse_mode=ParseMode.HTML)

    @support_router.message(F.chat.id == SUPPORT_GROUP_ID, F.message_thread_id, Command("info"))
    async def show_user_info(message: types.Message, bot: Bot):
        thread_id = message.message_thread_id
        user_id = database.get_user_id_by_thread(thread_id)

        if not user_id:
            await message.reply("❌ Пользователь не найден.")
            return

        user_data = database.get_user(user_id)
        if not user_data:
            await message.reply("❌ Данные пользователя не найдены.")
            return

        username = user_data.get('username', 'N/A')
        summary = await get_user_summary(user_id, username)
        await message.reply(summary, parse_mode=ParseMode.HTML)

    @support_router.callback_query(F.data.startswith("ticket_"))
    async def handle_ticket_action(callback: types.CallbackQuery, bot: Bot):
        action, user_id_str = callback.data.rsplit("_", 1)
        action = action.replace("ticket_", "")
        user_id = int(user_id_str)

        if action == "resolve":
            set_ticket_status(user_id, TicketStatus.RESOLVED)
            await callback.answer("✅ Тикет отмечен как решённый")
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text="✅ <b>Ваш вопрос отмечен как решённый.</b>\n\n"
                         "Если проблема не решена, просто напишите нам снова.",
                    parse_mode=ParseMode.HTML
                )
            except:
                pass

        elif action == "close":
            set_ticket_status(user_id, TicketStatus.CLOSED)
            await callback.answer("🔒 Тикет закрыт")
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text="🔒 <b>Ваш тикет был закрыт.</b>\n\n"
                         "Оцените качество поддержки:",
                    parse_mode=ParseMode.HTML,
                    reply_markup=create_rating_keyboard()
                )
            except:
                pass
            thread_id = database.get_support_thread_id(user_id)
            if thread_id:
                try:
                    await bot.close_forum_topic(chat_id=SUPPORT_GROUP_ID, message_thread_id=thread_id)
                except:
                    pass

        elif action == "wait":
            set_ticket_status(user_id, TicketStatus.WAITING_USER)
            await callback.answer("⏳ Ожидание ответа пользователя")
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text="⏳ <b>Ожидаем вашего ответа.</b>\n\n"
                         "Пожалуйста, предоставьте дополнительную информацию.",
                    parse_mode=ParseMode.HTML
                )
            except:
                pass

        elif action == "urgent":
            set_ticket_priority(user_id, TicketPriority.URGENT)
            await callback.answer("🔴 Приоритет: СРОЧНО")

        status = get_ticket_status(user_id)
        priority = get_ticket_priority(user_id)
        status_text = STATUS_EMOJI.get(TicketStatus(status), "❓") if status else "❓"
        priority_text = PRIORITY_EMOJI.get(TicketPriority(priority), "🟡") if priority else "🟡"

        try:
            await callback.message.edit_reply_markup(
                reply_markup=create_ticket_actions_keyboard(user_id)
            )
        except:
            pass

    @support_router.callback_query(F.data.startswith("rate_"))
    async def handle_rating(callback: types.CallbackQuery):
        rating = int(callback.data.replace("rate_", ""))
        user_id = callback.from_user.id

        database.save_support_rating(user_id, rating)

        stars = "⭐" * rating
        await callback.answer(f"Спасибо за оценку! {stars}")
        await callback.message.edit_text(
            f"✅ <b>Спасибо за вашу оценку!</b>\n\n"
            f"Ваша оценка: {stars}\n\n"
            f"Мы ценим ваше мнение и стараемся становиться лучше!",
            parse_mode=ParseMode.HTML
        )

        thread_id = database.get_support_thread_id(user_id)
        if thread_id and SUPPORT_GROUP_ID:
            try:
                await callback.bot.send_message(
                    chat_id=SUPPORT_GROUP_ID,
                    message_thread_id=thread_id,
                    text=f"📊 <b>Оценка от пользователя:</b> {stars} ({rating}/5)",
                    parse_mode=ParseMode.HTML
                )
            except:
                pass

    @support_router.message(F.chat.id == SUPPORT_GROUP_ID, F.message_thread_id)
    async def from_admin_to_user(message: types.Message, bot: Bot):
        thread_id = message.message_thread_id
        user_id = database.get_user_id_by_thread(thread_id)

        if message.from_user.id == bot.id:
            return

        if message.text and message.text.startswith("/"):
            return

        if not user_id:
            return

        status = get_ticket_status(user_id)
        if status == TicketStatus.OPEN.value:
            set_ticket_status(user_id, TicketStatus.IN_PROGRESS)

        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=SUPPORT_GROUP_ID,
                message_id=message.message_id
            )
        except TelegramBadRequest as e:
            if "bot was blocked" in str(e).lower() or "user is deactivated" in str(e).lower():
                await message.reply("⚠️ Пользователь заблокировал бота или деактивирован.")
            else:
                logger.error(f"Failed to send message to user {user_id}: {e}")
                await message.reply("❌ Не удалось доставить сообщение.")
        except Exception as e:
            logger.error(f"Failed to send message from thread {thread_id} to user {user_id}: {e}")
            await message.reply("❌ Не удалось доставить сообщение этому пользователю.")

    return support_router

import logging
import uuid
import qrcode
import aiohttp
import re
import hashlib
import json
import base64
import asyncio

from urllib.parse import urlencode
from hmac import compare_digest
from functools import wraps
from yookassa import Payment
from io import BytesIO
from datetime import datetime, timedelta
from aiosend import CryptoPay, TESTNET
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict

from aiogram import Bot, Router, F, types, html
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.types import BufferedInputFile
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ChatMemberStatus
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shop_bot.bot import keyboards
from shop_bot.modules import mwshark_api
from shop_bot.data_manager.database import (
    get_user, add_new_key, get_user_keys, update_user_stats,
    register_user_if_not_exists, get_next_key_number, get_key_by_id,
    update_key_info, set_trial_used, set_terms_agreed, get_setting,
    get_all_plans, get_plan_by_id, log_transaction, get_referral_count,
    add_to_referral_balance, create_pending_transaction, get_all_users,
    set_referral_balance, set_referral_balance_all
)

from shop_bot.config import (
    get_profile_text, get_vpn_active_text, VPN_INACTIVE_TEXT, VPN_NO_DATA_TEXT,
    get_key_info_text, CHOOSE_PAYMENT_METHOD_MESSAGE, get_purchase_success_text
)

TELEGRAM_BOT_USERNAME = None
ADMIN_ID = None

logger = logging.getLogger(__name__)
admin_router = Router()
user_router = Router()


class KeyPurchase(StatesGroup):
    waiting_for_plan_selection = State()


class Onboarding(StatesGroup):
    waiting_for_subscription_and_agreement = State()


class PaymentProcess(StatesGroup):
    waiting_for_email = State()
    waiting_for_payment_method = State()


class Broadcast(StatesGroup):
    waiting_for_message = State()
    waiting_for_button_option = State()
    waiting_for_button_text = State()
    waiting_for_button_url = State()
    waiting_for_confirmation = State()


class WithdrawStates(StatesGroup):
    waiting_for_details = State()


def is_valid_email(email: str) -> bool:
    pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    return re.match(pattern, email) is not None


async def show_main_menu(message: types.Message, edit_message: bool = False):
    user_id = message.chat.id
    user_db_data = get_user(user_id)
    user_keys = get_user_keys(user_id)

    trial_available = not (user_db_data and user_db_data.get('trial_used'))
    is_admin = str(user_id) == ADMIN_ID

    text = "🏠 <b>Главное меню</b>\n\nВыберите действие:"
    keyboard = keyboards.create_main_menu_keyboard(user_keys, trial_available, is_admin)

    if edit_message:
        try:
            await message.edit_text(text, reply_markup=keyboard)
        except TelegramBadRequest:
            pass
    else:
        await message.answer(text, reply_markup=keyboard)


def registration_required(f):
    @wraps(f)
    async def decorated_function(event: types.Update, *args, **kwargs):
        user_id = event.from_user.id
        user_data = get_user(user_id)
        if user_data:
            return await f(event, *args, **kwargs)
        else:
            message_text = "Пожалуйста, для начала работы отправьте команду /start"
            if isinstance(event, types.CallbackQuery):
                await event.answer(message_text, show_alert=True)
            else:
                await event.answer(message_text)
    return decorated_function


def get_user_router() -> Router:
    user_router = Router()

    @user_router.message(CommandStart())
    async def start_handler(message: types.Message, state: FSMContext, bot: Bot, command: CommandObject):
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.full_name
        referrer_id = None

        if command.args and command.args.startswith('ref_'):
            try:
                potential_referrer_id = int(command.args.split('_')[1])
                if potential_referrer_id != user_id:
                    referrer_id = potential_referrer_id
                    logger.info(f"New user {user_id} referred by {referrer_id}")
            except (IndexError, ValueError):
                logger.warning(f"Invalid referral code: {command.args}")

        register_user_if_not_exists(user_id, username, referrer_id)
        user_data = get_user(user_id)

        if user_data and user_data.get('agreed_to_terms'):
            await message.answer(
                f"👋 Снова здравствуйте, {html.bold(message.from_user.full_name)}!",
                reply_markup=keyboards.main_reply_keyboard
            )
            await show_main_menu(message)
            return

        terms_url = get_setting("terms_url")
        privacy_url = get_setting("privacy_url")
        channel_url = get_setting("channel_url")

        if not channel_url or not terms_url or not privacy_url:
            set_terms_agreed(user_id)
            await show_main_menu(message)
            return

        is_subscription_forced = get_setting("force_subscription") == "true"
        show_welcome_screen = (is_subscription_forced and channel_url) or (terms_url and privacy_url)

        if not show_welcome_screen:
            set_terms_agreed(user_id)
            await show_main_menu(message)
            return

        welcome_parts = ["<b>Добро пожаловать!</b>\n"]

        if is_subscription_forced and channel_url:
            welcome_parts.append("Для доступа ко всем функциям подпишитесь на наш канал.\n")

        if terms_url and privacy_url:
            welcome_parts.append("Ознакомьтесь с Условиями использования и Политикой конфиденциальности.")
        elif terms_url:
            welcome_parts.append("Ознакомьтесь с Условиями использования.")
        elif privacy_url:
            welcome_parts.append("Ознакомьтесь с Политикой конфиденциальности.")

        welcome_parts.append("\nПосле этого нажмите кнопку ниже.")

        await message.answer(
            "\n".join(welcome_parts),
            reply_markup=keyboards.create_welcome_keyboard(
                channel_url=channel_url,
                is_subscription_forced=is_subscription_forced,
                terms_url=terms_url,
                privacy_url=privacy_url
            ),
            disable_web_page_preview=True
        )
        await state.set_state(Onboarding.waiting_for_subscription_and_agreement)


    @user_router.callback_query(Onboarding.waiting_for_subscription_and_agreement, F.data == "check_subscription_and_agree")
    async def check_subscription_handler(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
        user_id = callback.from_user.id
        channel_url = get_setting("channel_url")
        is_subscription_forced = get_setting("force_subscription") == "true"

        if not is_subscription_forced or not channel_url:
            await process_successful_onboarding(callback, state)
            return

        try:
            if '@' not in channel_url and 't.me/' not in channel_url:
                logger.error(f"Invalid channel URL: {channel_url}")
                await process_successful_onboarding(callback, state)
                return

            channel_id = '@' + channel_url.split('/')[-1] if 't.me/' in channel_url else channel_url
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)

            if member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
                await process_successful_onboarding(callback, state)
            else:
                await callback.answer("Вы еще не подписались на канал.", show_alert=True)

        except Exception as e:
            logger.error(f"Subscription check error for {user_id}: {e}")
            await callback.answer("Не удалось проверить подписку.", show_alert=True)

    @user_router.message(Onboarding.waiting_for_subscription_and_agreement)
    async def onboarding_fallback_handler(message: types.Message):
        await message.answer("Выполните требуемые действия и нажмите кнопку выше.")

    @user_router.message(F.text == "🏠 Главное меню")
    @registration_required
    async def main_menu_handler(message: types.Message):
        await show_main_menu(message)

    @user_router.callback_query(F.data == "back_to_main_menu")
    @registration_required
    async def back_to_main_menu_handler(callback: types.CallbackQuery):
        await callback.answer()
        await show_main_menu(callback.message, edit_message=True)

    @user_router.callback_query(F.data == "show_profile")
    @registration_required
    async def profile_handler_callback(callback: types.CallbackQuery):
        await callback.answer()
        user_id = callback.from_user.id
        user_db_data = get_user(user_id)
        user_keys = get_user_keys(user_id)

        if not user_db_data:
            await callback.answer("Не удалось получить данные профиля.", show_alert=True)
            return

        username = html.bold(user_db_data.get('username', 'Пользователь'))
        total_spent = user_db_data.get('total_spent', 0)
        total_months = user_db_data.get('total_months', 0)
        now = datetime.now()
        active_keys = [key for key in user_keys if datetime.fromisoformat(key['expiry_date']) > now]

        if active_keys:
            latest_key = max(active_keys, key=lambda k: datetime.fromisoformat(k['expiry_date']))
            latest_expiry_date = datetime.fromisoformat(latest_key['expiry_date'])
            time_left = latest_expiry_date - now
            vpn_status_text = get_vpn_active_text(time_left.days, time_left.seconds // 3600)
        elif user_keys:
            vpn_status_text = VPN_INACTIVE_TEXT
        else:
            vpn_status_text = VPN_NO_DATA_TEXT

        final_text = get_profile_text(username, total_spent, total_months, vpn_status_text)
        await callback.message.edit_text(final_text, reply_markup=keyboards.create_back_to_menu_keyboard())


    @user_router.callback_query(F.data == "start_broadcast")
    @registration_required
    async def start_broadcast_handler(callback: types.CallbackQuery, state: FSMContext):
        if str(callback.from_user.id) != ADMIN_ID:
            await callback.answer("У вас нет прав.", show_alert=True)
            return

        await callback.answer()
        await callback.message.edit_text(
            "Пришлите сообщение для рассылки.\nПоддерживается форматирование и медиа.",
            reply_markup=keyboards.create_broadcast_cancel_keyboard()
        )
        await state.set_state(Broadcast.waiting_for_message)

    @user_router.message(Broadcast.waiting_for_message)
    async def broadcast_message_received_handler(message: types.Message, state: FSMContext):
        await state.update_data(message_to_send=message.model_dump_json())
        await message.answer(
            "Сообщение получено. Добавить кнопку со ссылкой?",
            reply_markup=keyboards.create_broadcast_options_keyboard()
        )
        await state.set_state(Broadcast.waiting_for_button_option)

    @user_router.callback_query(Broadcast.waiting_for_button_option, F.data == "broadcast_add_button")
    async def add_button_prompt_handler(callback: types.CallbackQuery, state: FSMContext):
        await callback.answer()
        await callback.message.edit_text(
            "Отправьте текст для кнопки.",
            reply_markup=keyboards.create_broadcast_cancel_keyboard()
        )
        await state.set_state(Broadcast.waiting_for_button_text)

    @user_router.message(Broadcast.waiting_for_button_text)
    async def button_text_received_handler(message: types.Message, state: FSMContext):
        await state.update_data(button_text=message.text)
        await message.answer(
            "Теперь отправьте URL для кнопки.",
            reply_markup=keyboards.create_broadcast_cancel_keyboard()
        )
        await state.set_state(Broadcast.waiting_for_button_url)

    @user_router.message(Broadcast.waiting_for_button_url)
    async def button_url_received_handler(message: types.Message, state: FSMContext, bot: Bot):
        url_to_check = message.text
        is_valid = await is_url_reachable(url_to_check)

        if not is_valid:
            await message.answer("❌ Ссылка недоступна. Попробуйте еще раз.")
            return

        await state.update_data(button_url=url_to_check)
        await show_broadcast_preview(message, state, bot)

    @user_router.callback_query(Broadcast.waiting_for_button_option, F.data == "broadcast_skip_button")
    async def skip_button_handler(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
        await callback.answer()
        await state.update_data(button_text=None, button_url=None)
        await show_broadcast_preview(callback.message, state, bot)

    async def show_broadcast_preview(message: types.Message, state: FSMContext, bot: Bot):
        data = await state.get_data()
        message_json = data.get('message_to_send')
        original_message = types.Message.model_validate_json(message_json)

        button_text = data.get('button_text')
        button_url = data.get('button_url')

        preview_keyboard = None
        if button_text and button_url:
            builder = InlineKeyboardBuilder()
            builder.button(text=button_text, url=button_url)
            preview_keyboard = builder.as_markup()

        await message.answer(
            "Превью сообщения. Отправляем?",
            reply_markup=keyboards.create_broadcast_confirmation_keyboard()
        )

        await bot.copy_message(
            chat_id=message.chat.id,
            from_chat_id=original_message.chat.id,
            message_id=original_message.message_id,
            reply_markup=preview_keyboard
        )
        await state.set_state(Broadcast.waiting_for_confirmation)


    @user_router.callback_query(Broadcast.waiting_for_confirmation, F.data == "confirm_broadcast")
    async def confirm_broadcast_handler(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
        await callback.message.edit_text("⏳ Начинаю рассылку...")

        data = await state.get_data()
        message_json = data.get('message_to_send')
        original_message = types.Message.model_validate_json(message_json)

        button_text = data.get('button_text')
        button_url = data.get('button_url')

        final_keyboard = None
        if button_text and button_url:
            builder = InlineKeyboardBuilder()
            builder.button(text=button_text, url=button_url)
            final_keyboard = builder.as_markup()

        await state.clear()

        users = get_all_users()
        sent_count = 0
        failed_count = 0
        banned_count = 0

        for user in users:
            user_id = user['telegram_id']
            if user.get('is_banned'):
                banned_count += 1
                continue

            try:
                await bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=original_message.chat.id,
                    message_id=original_message.message_id,
                    reply_markup=final_keyboard
                )
                sent_count += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                failed_count += 1
                logger.warning(f"Broadcast failed for {user_id}: {e}")

        await callback.message.answer(
            f"✅ Рассылка завершена!\n\n👍 Отправлено: {sent_count}\n👎 Ошибок: {failed_count}\n🚫 Пропущено: {banned_count}"
        )
        await show_main_menu(callback.message)

    @user_router.callback_query(StateFilter(Broadcast), F.data == "cancel_broadcast")
    async def cancel_broadcast_handler(callback: types.CallbackQuery, state: FSMContext):
        await callback.answer("Рассылка отменена.")
        await state.clear()
        await show_main_menu(callback.message, edit_message=True)

    @user_router.callback_query(F.data == "show_referral_program")
    @registration_required
    async def referral_program_handler(callback: types.CallbackQuery):
        await callback.answer()
        user_id = callback.from_user.id
        user_data = get_user(user_id)
        bot_username = (await callback.bot.get_me()).username

        referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        referral_count = get_referral_count(user_id)
        balance = float(user_data.get('referral_balance', 0) or 0)

        text = (
            "🤝 <b>Реферальная программа</b>\n\n"
            "Приглашайте друзей и получайте вознаграждение!\n\n"
            f"<b>Ваша ссылка:</b>\n<code>{referral_link}</code>\n\n"
            f"<b>Приглашено:</b> {referral_count}\n"
            f"<b>Баланс:</b> {balance:.2f} RUB"
        )

        builder = InlineKeyboardBuilder()
        if balance >= 100:
            builder.button(text="💸 Заявка на вывод", callback_data="withdraw_request")
        builder.button(text="⬅️ Назад", callback_data="back_to_main_menu")
        builder.adjust(1)
        await callback.message.edit_text(text, reply_markup=builder.as_markup())


    @user_router.callback_query(F.data == "withdraw_request")
    @registration_required
    async def withdraw_request_handler(callback: types.CallbackQuery, state: FSMContext):
        await callback.answer()
        await callback.message.edit_text("Отправьте реквизиты для вывода:")
        await state.set_state(WithdrawStates.waiting_for_details)

    @user_router.message(WithdrawStates.waiting_for_details)
    @registration_required
    async def process_withdraw_details(message: types.Message, state: FSMContext):
        user_id = message.from_user.id
        user = get_user(user_id)
        balance = float(user.get('referral_balance', 0) or 0)
        details = message.text.strip()

        if balance < 100:
            await message.answer("❌ Баланс менее 100 руб.")
            await state.clear()
            return

        admin_id = int(get_setting("admin_telegram_id"))
        text = (
            f"💸 <b>Заявка на вывод</b>\n"
            f"👤 @{user.get('username', 'N/A')} (ID: <code>{user_id}</code>)\n"
            f"💰 Сумма: <b>{balance:.2f} RUB</b>\n"
            f"📄 Реквизиты: <code>{details}</code>\n\n"
            f"/approve_withdraw_{user_id} /decline_withdraw_{user_id}"
        )
        await message.answer("Заявка отправлена администратору.")
        await message.bot.send_message(admin_id, text, parse_mode="HTML")
        await state.clear()

    @user_router.message(Command(commands=["approve_withdraw"]))
    async def approve_withdraw_handler(message: types.Message):
        admin_id = int(get_setting("admin_telegram_id"))
        if message.from_user.id != admin_id:
            return
        try:
            user_id = int(message.text.split("_")[-1])
            user = get_user(user_id)
            balance = float(user.get('referral_balance', 0) or 0)
            if balance < 100:
                await message.answer("Баланс менее 100 руб.")
                return
            set_referral_balance(user_id, 0)
            set_referral_balance_all(user_id, 0)
            await message.answer(f"✅ Выплата {balance:.2f} RUB подтверждена.")
            await message.bot.send_message(user_id, f"✅ Заявка на {balance:.2f} RUB одобрена.")
        except Exception as e:
            await message.answer(f"Ошибка: {e}")

    @user_router.message(Command(commands=["decline_withdraw"]))
    async def decline_withdraw_handler(message: types.Message):
        admin_id = int(get_setting("admin_telegram_id"))
        if message.from_user.id != admin_id:
            return
        try:
            user_id = int(message.text.split("_")[-1])
            await message.answer(f"❌ Заявка {user_id} отклонена.")
            await message.bot.send_message(user_id, "❌ Заявка на вывод отклонена.")
        except Exception as e:
            await message.answer(f"Ошибка: {e}")

    @user_router.callback_query(F.data == "show_about")
    @registration_required
    async def about_handler(callback: types.CallbackQuery):
        await callback.answer()
        about_text = get_setting("about_text") or "Информация не добавлена."
        keyboard = keyboards.create_about_keyboard(
            get_setting("channel_url"),
            get_setting("terms_url"),
            get_setting("privacy_url")
        )
        await callback.message.edit_text(about_text, reply_markup=keyboard, disable_web_page_preview=True)

    @user_router.callback_query(F.data == "show_help")
    @registration_required
    async def help_handler(callback: types.CallbackQuery):
        await callback.answer()
        support_user = get_setting("support_user")
        support_text = get_setting("support_text")

        if not support_user and not support_text:
            await callback.message.edit_text(
                "Информация о поддержке не установлена.",
                reply_markup=keyboards.create_back_to_menu_keyboard()
            )
        elif not support_text:
            await callback.message.edit_text(
                "Для связи с поддержкой используйте кнопку ниже.",
                reply_markup=keyboards.create_support_keyboard(support_user)
            )
        else:
            await callback.message.edit_text(
                support_text,
                reply_markup=keyboards.create_support_keyboard(support_user)
            )


    @user_router.callback_query(F.data == "manage_keys")
    @registration_required
    async def manage_keys_handler(callback: types.CallbackQuery):
        await callback.answer()
        user_keys = get_user_keys(callback.from_user.id)
        await callback.message.edit_text(
            "Ваши ключи:" if user_keys else "У вас пока нет ключей.",
            reply_markup=keyboards.create_keys_management_keyboard(user_keys)
        )

    @user_router.callback_query(F.data == "get_trial")
    @registration_required
    async def trial_period_handler(callback: types.CallbackQuery, state: FSMContext):
        user_id = callback.from_user.id
        user_db_data = get_user(user_id)

        if user_db_data and user_db_data.get('trial_used'):
            await callback.answer("Вы уже использовали пробный период.", show_alert=True)
            return

        api_key = get_setting("mwshark_api_key")
        if not api_key:
            await callback.message.edit_text(
                "❌ API ключ не настроен.",
                reply_markup=keyboards.create_back_to_menu_keyboard()
            )
            return

        await callback.answer()
        trial_days = int(get_setting("trial_duration_days") or "3")
        await callback.message.edit_text("⏳ *Загружаю...*", parse_mode="Markdown")

        try:
            result = await mwshark_api.create_subscription_for_user(
                api_key=api_key, user_id=user_id, days=trial_days
            )

            if not result.get('success'):
                await callback.message.edit_text(
                    f"❌ Ошибка: {result.get('error', 'Неизвестная ошибка')}",
                    reply_markup=keyboards.create_back_to_menu_keyboard()
                )
                return

            set_trial_used(user_id)

            subscription = result.get('subscription', {})
            subscription_uuid = subscription.get('uuid', '')
            expiry_str = subscription.get('expiry_date', '')
            expiry_date = datetime.fromisoformat(expiry_str.replace('+00:00', ''))
            expiry_ms = int(expiry_date.timestamp() * 1000)
            subscription_link = subscription.get('link', '')

            new_key_id = add_new_key(user_id=user_id, subscription_link=subscription_link, expiry_timestamp_ms=expiry_ms, subscription_uuid=subscription_uuid)

            await callback.message.delete()
            final_text = get_purchase_success_text("создан", 1, expiry_date, subscription_link)
            await callback.message.answer(text=final_text, reply_markup=keyboards.create_key_info_keyboard(new_key_id))

        except Exception as e:
            logger.error(f"Trial key error for {user_id}: {e}", exc_info=True)
            await callback.message.edit_text(
                "❌ Ошибка при создании ключа.",
                reply_markup=keyboards.create_back_to_menu_keyboard()
            )

    @user_router.callback_query(F.data.startswith("show_key_"))
    @registration_required
    async def show_key_handler(callback: types.CallbackQuery):
        try:
            key_id_str = callback.data.split("_")[2]
            if key_id_str == "None" or not key_id_str:
                await callback.answer("❌ Ключ не найден.", show_alert=True)
                return
            key_id = int(key_id_str)
        except (IndexError, ValueError):
            await callback.answer("❌ Неверный формат ключа.", show_alert=True)
            return
            
        user_id = callback.from_user.id
        key_data = get_key_by_id(key_id)

        if not key_data or key_data['user_id'] != user_id:
            await callback.message.edit_text("❌ Ключ не найден.")
            return

        try:
            subscription_link = key_data.get('subscription_link', '')
            expiry_date = datetime.fromisoformat(key_data['expiry_date'])
            created_date = datetime.fromisoformat(key_data['created_date'])

            all_user_keys = get_user_keys(user_id)
            key_number = next((i + 1 for i, key in enumerate(all_user_keys) if key['key_id'] == key_id), 0)

            final_text = get_key_info_text(key_number, expiry_date, created_date, subscription_link)
            await callback.message.edit_text(text=final_text, reply_markup=keyboards.create_key_info_keyboard(key_id))
        except Exception as e:
            logger.error(f"Show key error {key_id}: {e}")
            await callback.message.edit_text("❌ Ошибка получения данных.")


    @user_router.callback_query(F.data.startswith("show_qr_"))
    @registration_required
    async def show_qr_handler(callback: types.CallbackQuery):
        try:
            key_id_str = callback.data.split("_")[2]
            if key_id_str == "None" or not key_id_str:
                await callback.answer("❌ Ключ не найден.", show_alert=True)
                return
            key_id = int(key_id_str)
        except (IndexError, ValueError):
            await callback.answer("❌ Неверный формат ключа.", show_alert=True)
            return
            
        await callback.answer("Генерирую QR-код...")
        key_data = get_key_by_id(key_id)

        if not key_data or key_data['user_id'] != callback.from_user.id:
            return

        try:
            subscription_link = key_data.get('subscription_link', '')
            if not subscription_link:
                await callback.answer("Ошибка генерации QR.", show_alert=True)
                return

            qr_img = qrcode.make(subscription_link)
            bio = BytesIO()
            qr_img.save(bio, "PNG")
            bio.seek(0)
            qr_code_file = BufferedInputFile(bio.read(), filename="vpn_qr.png")
            await callback.message.answer_photo(photo=qr_code_file)
        except Exception as e:
            logger.error(f"QR error for key {key_id}: {e}")

    @user_router.callback_query(F.data.startswith("howto_vless_"))
    @registration_required
    async def show_instruction_key_handler(callback: types.CallbackQuery):
        await callback.answer()
        try:
            key_id_str = callback.data.split("_")[2]
            if key_id_str == "None" or not key_id_str:
                key_id = None
            else:
                key_id = int(key_id_str)
        except (IndexError, ValueError):
            key_id = None
            
        await callback.message.edit_text(
            "Выберите платформу:",
            reply_markup=keyboards.create_howto_vless_keyboard_key(
                android_url=get_setting("android_url"),
                windows_url=get_setting("windows_url"),
                ios_url=get_setting("ios_url"),
                linux_url=get_setting("linux_url"),
                key_id=key_id
            ),
            disable_web_page_preview=False
        )

    @user_router.callback_query(F.data == "howto_vless")
    @registration_required
    async def show_instruction_handler(callback: types.CallbackQuery):
        await callback.answer()
        await callback.message.edit_text(
            "Выберите платформу:",
            reply_markup=keyboards.create_howto_vless_keyboard(
                android_url=get_setting("android_url"),
                windows_url=get_setting("windows_url"),
                ios_url=get_setting("ios_url"),
                linux_url=get_setting("linux_url")
            ),
            disable_web_page_preview=False
        )

    @user_router.callback_query(F.data == "buy_new_key")
    @registration_required
    async def buy_new_key_handler(callback: types.CallbackQuery):
        await callback.answer()
        plans = get_all_plans()
        if not plans:
            await callback.message.edit_text("❌ Нет доступных тарифов.", reply_markup=keyboards.create_back_to_menu_keyboard())
            return
        await callback.message.edit_text("Выберите тариф:", reply_markup=keyboards.create_plans_keyboard(plans, action="new"))

    @user_router.callback_query(F.data.startswith("extend_key_"))
    @registration_required
    async def extend_key_handler(callback: types.CallbackQuery):
        await callback.answer()
        try:
            key_id = int(callback.data.split("_")[2])
        except (IndexError, ValueError):
            await callback.message.edit_text("❌ Неверный формат ключа.")
            return

        key_data = get_key_by_id(key_id)
        if not key_data or key_data['user_id'] != callback.from_user.id:
            await callback.message.edit_text("❌ Ключ не найден.")
            return

        plans = get_all_plans()
        if not plans:
            await callback.message.edit_text("❌ Нет доступных тарифов.", reply_markup=keyboards.create_back_to_menu_keyboard())
            return

        await callback.message.edit_text(
            "Выберите тариф для продления:",
            reply_markup=keyboards.create_plans_keyboard(plans, action="extend", key_id=key_id)
        )


    @user_router.callback_query(F.data.startswith("buy_"))
    @registration_required
    async def plan_selection_handler(callback: types.CallbackQuery, state: FSMContext):
        await callback.answer()
        parts = callback.data.split("_")
        plan_id = int(parts[1])
        action = parts[2]
        key_id = int(parts[3])

        await state.update_data(action=action, key_id=key_id, plan_id=plan_id)
        await callback.message.edit_text(
            "📧 Введите email для чека или нажмите кнопку ниже.",
            reply_markup=keyboards.create_skip_email_keyboard()
        )
        await state.set_state(PaymentProcess.waiting_for_email)

    @user_router.callback_query(PaymentProcess.waiting_for_email, F.data == "back_to_plans")
    async def back_to_plans_handler(callback: types.CallbackQuery, state: FSMContext):
        data = await state.get_data()
        await state.clear()
        action = data.get('action')
        if action == 'new':
            await buy_new_key_handler(callback)
        elif action == 'extend':
            callback.data = f"extend_key_{data.get('key_id')}"
            await extend_key_handler(callback)
        else:
            await back_to_main_menu_handler(callback)

    @user_router.message(PaymentProcess.waiting_for_email)
    async def process_email_handler(message: types.Message, state: FSMContext):
        if is_valid_email(message.text):
            await state.update_data(customer_email=message.text)
            await message.answer(f"✅ Email: {message.text}")
            data = await state.get_data()
            await message.answer(
                CHOOSE_PAYMENT_METHOD_MESSAGE,
                reply_markup=keyboards.create_payment_method_keyboard(
                    action=data.get('action'),
                    key_id=data.get('key_id')
                )
            )
            await state.set_state(PaymentProcess.waiting_for_payment_method)
        else:
            await message.answer("❌ Неверный формат email.")

    @user_router.callback_query(PaymentProcess.waiting_for_email, F.data == "skip_email")
    async def skip_email_handler(callback: types.CallbackQuery, state: FSMContext):
        await callback.answer()
        await state.update_data(customer_email=None)
        data = await state.get_data()
        await callback.message.edit_text(
            CHOOSE_PAYMENT_METHOD_MESSAGE,
            reply_markup=keyboards.create_payment_method_keyboard(
                action=data.get('action'),
                key_id=data.get('key_id')
            )
        )
        await state.set_state(PaymentProcess.waiting_for_payment_method)

    @user_router.callback_query(PaymentProcess.waiting_for_payment_method, F.data == "back_to_email_prompt")
    async def back_to_email_prompt_handler(callback: types.CallbackQuery, state: FSMContext):
        await callback.message.edit_text(
            "📧 Введите email для чека или нажмите кнопку ниже.",
            reply_markup=keyboards.create_skip_email_keyboard()
        )
        await state.set_state(PaymentProcess.waiting_for_email)


    @user_router.callback_query(PaymentProcess.waiting_for_payment_method, F.data == "pay_yookassa")
    async def create_yookassa_payment_handler(callback: types.CallbackQuery, state: FSMContext):
        await callback.answer("Создаю ссылку...")
        data = await state.get_data()
        user_data = get_user(callback.from_user.id)
        plan = get_plan_by_id(data.get('plan_id'))

        if not plan:
            await callback.message.answer("Ошибка выбора тарифа.")
            await state.clear()
            return

        base_price = Decimal(str(plan['price']))
        price_rub = base_price

        if user_data.get('referred_by') and user_data.get('total_spent', 0) == 0:
            discount = Decimal(get_setting("referral_discount") or "0")
            if discount > 0:
                price_rub = base_price - (base_price * discount / 100).quantize(Decimal("0.01"))

        customer_email = data.get('customer_email')
        action = data.get('action')
        key_id = data.get('key_id')
        days = plan['days']
        user_id = callback.from_user.id

        if not customer_email:
            customer_email = get_setting("receipt_email")

        try:
            price_str = f"{price_rub:.2f}"
            receipt = None
            if customer_email and is_valid_email(customer_email):
                receipt = {
                    "customer": {"email": customer_email},
                    "items": [{
                        "description": f"Подписка на {days} дн.",
                        "quantity": "1.00",
                        "amount": {"value": price_str, "currency": "RUB"},
                        "vat_code": "1"
                    }]
                }

            payment_payload = {
                "amount": {"value": price_str, "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": f"https://t.me/{TELEGRAM_BOT_USERNAME}"},
                "capture": True,
                "description": f"Подписка на {days} дн.",
                "metadata": {
                    "user_id": user_id, "days": days, "price": float(price_rub),
                    "action": action, "key_id": key_id, "plan_id": data.get('plan_id'),
                    "customer_email": customer_email, "payment_method": "YooKassa"
                }
            }
            if receipt:
                payment_payload['receipt'] = receipt

            payment = Payment.create(payment_payload, uuid.uuid4())
            await state.clear()
            await callback.message.edit_text(
                "Нажмите для оплаты:",
                reply_markup=keyboards.create_payment_keyboard(payment.confirmation.confirmation_url)
            )
        except Exception as e:
            logger.error(f"YooKassa payment error: {e}", exc_info=True)
            await callback.message.answer("Не удалось создать ссылку.")
            await state.clear()


    @user_router.callback_query(PaymentProcess.waiting_for_payment_method, F.data == "pay_cryptobot")
    async def create_cryptobot_invoice_handler(callback: types.CallbackQuery, state: FSMContext):
        await callback.answer("Создаю счет...")
        data = await state.get_data()
        user_data = get_user(callback.from_user.id)
        plan = get_plan_by_id(data.get('plan_id'))

        cryptobot_token = get_setting('cryptobot_token')
        if not cryptobot_token or len(cryptobot_token) < 10:
            await callback.message.edit_text("❌ Криптооплата недоступна. Токен не настроен.")
            await state.clear()
            return

        if not plan:
            await callback.message.edit_text("❌ Ошибка тарифа.")
            await state.clear()
            return

        base_price = Decimal(str(plan['price']))
        price_rub = base_price

        if user_data.get('referred_by') and user_data.get('total_spent', 0) == 0:
            discount = Decimal(get_setting("referral_discount") or "0")
            if discount > 0:
                price_rub = base_price - (base_price * discount / 100).quantize(Decimal("0.01"))

        user_id = callback.from_user.id
        days = plan['days']

        try:
            crypto = CryptoPay(cryptobot_token)
            
            metadata = {
                "user_id": user_id, "days": days, "price": float(price_rub),
                "action": data.get('action'), "key_id": data.get('key_id'),
                "plan_id": data.get('plan_id'),
                "customer_email": data.get('customer_email'), "payment_method": "CryptoBot"
            }
            payload_data = f"{user_id}:{days}:{float(price_rub)}:{data.get('action')}:{data.get('key_id')}:{data.get('plan_id')}:{data.get('customer_email')}:CryptoBot"

            invoice = await crypto.create_invoice(
                currency_type="fiat", fiat="RUB", amount=float(price_rub),
                description=f"Подписка на {days} дн.", payload=payload_data, expires_in=3600
            )

            if not invoice or not invoice.pay_url:
                raise Exception("Invoice creation failed")

            from shop_bot.data_manager.database import create_pending_cryptobot_invoice
            create_pending_cryptobot_invoice(str(invoice.invoice_id), json.dumps(metadata))

            await callback.message.edit_text("Нажмите для оплаты:", reply_markup=keyboards.create_payment_keyboard(invoice.pay_url))
            await state.clear()

        except Exception as e:
            logger.error(f"CryptoBot error for {user_id}: {e}", exc_info=True)
            await callback.message.edit_text("❌ Ошибка создания счета. Проверьте настройки CryptoBot.")
            await state.clear()

    @user_router.callback_query(PaymentProcess.waiting_for_payment_method, F.data == "pay_heleket")
    async def create_heleket_invoice_handler(callback: types.CallbackQuery, state: FSMContext):
        await callback.answer("Создаю счет...")
        data = await state.get_data()
        plan = get_plan_by_id(data.get('plan_id'))
        user_data = get_user(callback.from_user.id)

        if not plan:
            await callback.message.edit_text("❌ Ошибка тарифа.")
            await state.clear()
            return

        base_price = Decimal(str(plan['price']))
        price_rub = base_price

        if user_data.get('referred_by') and user_data.get('total_spent', 0) == 0:
            discount = Decimal(get_setting("referral_discount") or "0")
            if discount > 0:
                price_rub = base_price - (base_price * discount / 100).quantize(Decimal("0.01"))

        pay_url = await _create_heleket_payment_request(
            user_id=callback.from_user.id,
            price=float(price_rub),
            days=plan['days'],
            state_data=data
        )

        if pay_url:
            await callback.message.edit_text("Нажмите для оплаты:", reply_markup=keyboards.create_payment_keyboard(pay_url))
            await state.clear()
        else:
            await callback.message.edit_text("❌ Ошибка Heleket.")

    @user_router.callback_query(PaymentProcess.waiting_for_payment_method, F.data == "pay_platega")
    async def create_platega_invoice_handler(callback: types.CallbackQuery, state: FSMContext):
        await callback.answer("Создаю счет...")
        data = await state.get_data()
        plan = get_plan_by_id(data.get('plan_id'))
        user_data = get_user(callback.from_user.id)

        if not plan:
            await callback.message.edit_text("❌ Ошибка тарифа.")
            await state.clear()
            return

        base_price = Decimal(str(plan['price']))
        price_rub = base_price

        if user_data.get('referred_by') and user_data.get('total_spent', 0) == 0:
            discount = Decimal(get_setting("referral_discount") or "0")
            if discount > 0:
                price_rub = base_price - (base_price * discount / 100).quantize(Decimal("0.01"))

        result = await _create_platega_payment(
            user_id=callback.from_user.id,
            price=float(price_rub),
            days=plan['days'],
            state_data=data
        )

        if result and result.get('redirect'):
            await callback.message.edit_text("Нажмите для оплаты:", reply_markup=keyboards.create_payment_keyboard(result['redirect']))
            await state.clear()
        else:
            await callback.message.edit_text("❌ Ошибка Platega.")
            await state.clear()

    return user_router


async def process_successful_onboarding(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("✅ Доступ предоставлен.")
    set_terms_agreed(callback.from_user.id)
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("Приятного использования!", reply_markup=keyboards.main_reply_keyboard)
    await show_main_menu(callback.message)


async def is_url_reachable(url: str) -> bool:
    pattern = re.compile(r'^(https?://)(([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,})(/.*)?$')
    if not re.match(pattern, url):
        return False
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.head(url, allow_redirects=True) as response:
                return response.status < 400
    except Exception as e:
        logger.warning(f"URL validation failed for {url}: {e}")
        return False


async def notify_admin_of_purchase(bot: Bot, metadata: dict):
    if not ADMIN_ID:
        return
    try:
        user_id = metadata.get('user_id')
        price = float(metadata.get('price'))
        plan_id = metadata.get('plan_id')
        payment_method = metadata.get('payment_method', 'Unknown')

        user_info = get_user(user_id)
        plan_info = get_plan_by_id(plan_id)

        username = user_info.get('username', 'N/A') if user_info else 'N/A'
        plan_name = plan_info.get('plan_name', 'N/A') if plan_info else 'N/A'

        text = (
            f"🎉 **Новая покупка!**\n\n"
            f"👤 @{username} (ID: `{user_id}`)\n"
            f"📄 {plan_name}\n"
            f"💰 {price:.2f} RUB\n"
            f"💳 {payment_method}"
        )
        await bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Admin notification error: {e}", exc_info=True)


async def _create_heleket_payment_request(user_id: int, price: float, days: int, state_data: dict) -> str | None:
    merchant_id = get_setting("heleket_merchant_id")
    api_key = get_setting("heleket_api_key")
    bot_username = get_setting("telegram_bot_username")
    domain = get_setting("domain")

    if not all([merchant_id, api_key, bot_username, domain]):
        logger.error("Heleket: Missing settings.")
        return None

    redirect_url = f"https://t.me/{bot_username}"
    order_id = str(uuid.uuid4())

    metadata = {
        "user_id": user_id, "days": days, "price": float(price),
        "action": state_data.get('action'), "key_id": state_data.get('key_id'),
        "plan_id": state_data.get('plan_id'),
        "customer_email": state_data.get('customer_email'), "payment_method": "Heleket"
    }

    payload = {
        "amount": f"{price:.2f}", "currency": "RUB", "order_id": order_id,
        "description": json.dumps(metadata), "url_return": redirect_url,
        "url_success": redirect_url, "url_callback": f"https://{domain}/heleket-webhook",
        "lifetime": 1800, "is_payment_multiple": False
    }

    headers = {
        "merchant": merchant_id,
        "sign": _generate_heleket_signature(json.dumps(payload), api_key),
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.heleket.com/v1/payment", json=payload, headers=headers) as response:
                result = await response.json()
                if response.status == 200 and result.get("result", {}).get("url"):
                    return result["result"]["url"]
                logger.error(f"Heleket API Error: {response.status}, {result}")
                return None
    except Exception as e:
        logger.error(f"Heleket request failed: {e}", exc_info=True)
        return None


def _generate_heleket_signature(data, api_key: str) -> str:
    data_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if isinstance(data, dict) else str(data)
    base64_encoded = base64.b64encode(data_str.encode()).decode()
    return hashlib.md5(f"{base64_encoded}{api_key}".encode()).hexdigest()


async def _create_platega_payment(user_id: int, price: float, days: int, state_data: dict) -> dict | None:
    merchant_id = get_setting("platega_merchant_id")
    secret_key = get_setting("platega_secret_key")
    bot_username = get_setting("telegram_bot_username")
    domain = get_setting("domain")

    if not all([merchant_id, secret_key]):
        logger.error("Platega: Missing settings.")
        return None

    return_url = f"https://t.me/{bot_username}" if bot_username else "https://t.me"

    metadata = {
        "user_id": user_id, "days": days, "price": float(price),
        "action": state_data.get('action'), "key_id": state_data.get('key_id'),
        "plan_id": state_data.get('plan_id'),
        "customer_email": state_data.get('customer_email'), "payment_method": "Platega"
    }

    payload = {
        "paymentMethod": int(get_setting("platega_payment_method") or "2"),
        "paymentDetails": {"amount": int(price), "currency": "RUB"},
        "description": f"Подписка на {days} дн.",
        "return": return_url,
        "failedUrl": return_url,
        "payload": json.dumps(metadata)
    }

    headers = {
        "X-MerchantId": merchant_id,
        "X-Secret": secret_key,
        "Content-Type": "application/json"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://app.platega.io/transaction/process", json=payload, headers=headers) as response:
                result = await response.json()
                if response.status == 200 and result.get("redirect"):
                    from shop_bot.data_manager.database import create_pending_platega_transaction
                    create_pending_platega_transaction(result.get("transactionId"), json.dumps(metadata))
                    return result
                logger.error(f"Platega API Error: {response.status}, {result}")
                return None
    except Exception as e:
        logger.error(f"Platega request failed: {e}", exc_info=True)
        return None


async def check_platega_payment_status(transaction_id: str) -> dict | None:
    merchant_id = get_setting("platega_merchant_id")
    secret_key = get_setting("platega_secret_key")

    if not all([merchant_id, secret_key]):
        return None

    headers = {
        "X-MerchantId": merchant_id,
        "X-Secret": secret_key
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://app.platega.io/transaction/{transaction_id}", headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                return None
    except Exception as e:
        logger.error(f"Platega status check failed: {e}")
        return None


async def get_usdt_rub_rate() -> Decimal | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": "USDTRUB"}) as response:
                response.raise_for_status()
                data = await response.json()
                price_str = data.get('price')
                return Decimal(price_str) if price_str else None
    except Exception as e:
        logger.error(f"Binance rate error: {e}", exc_info=True)
        return None


async def process_successful_payment(bot: Bot, metadata: dict):
    try:
        user_id = int(metadata['user_id'])
        days = int(metadata['days'])
        price = float(metadata['price'])
        action = metadata['action']
        key_id = int(metadata['key_id'])
        plan_id = int(metadata['plan_id'])
        customer_email = metadata.get('customer_email')
        payment_method = metadata.get('payment_method')
    except (ValueError, TypeError) as e:
        logger.error(f"Metadata parse error: {e}. Metadata: {metadata}")
        return

    processing_message = await bot.send_message(chat_id=user_id, text="⏳ *Загружаю...*", parse_mode="Markdown")

    try:
        api_key = get_setting("mwshark_api_key")
        if not api_key:
            await processing_message.edit_text("❌ Ошибка конфигурации.")
            return

        if action == "new":
            result = await mwshark_api.create_subscription_for_user(
                api_key=api_key, user_id=user_id, days=days
            )
        elif action == "extend":
            key_data = get_key_by_id(key_id)
            if not key_data or not key_data.get('subscription_uuid'):
                await processing_message.edit_text("❌ UUID подписки не найден.")
                return
            result = await mwshark_api.extend_subscription_for_user(api_key=api_key, uuid=key_data['subscription_uuid'], days=days)
        else:
            await processing_message.edit_text("❌ Неизвестное действие.")
            return

        if not result.get('success'):
            await processing_message.edit_text(f"❌ API ошибка: {result.get('error', 'Неизвестная ошибка')}")
            return

        subscription = result.get('subscription', {})
        subscription_uuid = subscription.get('uuid', '')
        expiry_str = subscription.get('expiry_date', '')
        expiry_date = datetime.fromisoformat(expiry_str.replace('+00:00', ''))
        expiry_ms = int(expiry_date.timestamp() * 1000)
        subscription_link = subscription.get('link', '')

        if action == "new":
            key_id = add_new_key(user_id, subscription_link, expiry_ms, subscription_uuid)
        elif action == "extend":
            update_key_info(key_id, subscription_link, expiry_ms, subscription_uuid)

        user_data = get_user(user_id)
        referrer_id = user_data.get('referred_by') if user_data else None

        if referrer_id:
            percentage = Decimal(get_setting("referral_percentage") or "0")
            reward = (Decimal(str(price)) * percentage / 100).quantize(Decimal("0.01"))

            if float(reward) > 0:
                add_to_referral_balance(referrer_id, float(reward))
                try:
                    referrer_username = user_data.get('username', 'пользователь')
                    await bot.send_message(
                        referrer_id,
                        f"🎉 Реферал @{referrer_username} совершил покупку!\n💰 Начислено: {reward:.2f} RUB."
                    )
                except Exception as e:
                    logger.warning(f"Referral notification failed for {referrer_id}: {e}")

        months_approx = max(1, days // 30)
        update_user_stats(user_id, price, months_approx)

        user_info = get_user(user_id)
        internal_payment_id = str(uuid.uuid4())
        log_username = user_info.get('username', 'N/A') if user_info else 'N/A'
        plan_info = get_plan_by_id(plan_id)

        log_metadata = json.dumps({
            "plan_id": plan_id,
            "plan_name": plan_info.get('plan_name', 'Unknown') if plan_info else 'Unknown',
            "customer_email": customer_email
        })

        log_transaction(
            username=log_username, transaction_id=None, payment_id=internal_payment_id,
            user_id=user_id, status='paid', amount_rub=float(price),
            amount_currency=None, currency_name=None,
            payment_method=payment_method or 'Unknown', metadata=log_metadata
        )

        await processing_message.delete()

        all_user_keys = get_user_keys(user_id)
        key_number = next((i + 1 for i, key in enumerate(all_user_keys) if key['key_id'] == key_id), len(all_user_keys))

        final_text = get_purchase_success_text(
            action="создан" if action == "new" else "продлен",
            key_number=key_number,
            expiry_date=expiry_date,
            connection_string=subscription_link
        )

        await bot.send_message(chat_id=user_id, text=final_text, reply_markup=keyboards.create_key_info_keyboard(key_id))
        await notify_admin_of_purchase(bot, metadata)

    except Exception as e:
        logger.error(f"Payment processing error for {user_id}: {e}", exc_info=True)
        await processing_message.edit_text("❌ Ошибка выдачи ключа.")

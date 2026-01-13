import os
import logging
import asyncio
import json
import hashlib
import hmac
import base64
import subprocess
import platform
import psutil
from hmac import compare_digest
from datetime import datetime, timedelta
from functools import wraps
from math import ceil
from flask import Flask, request, render_template, redirect, url_for, flash, session, current_app, jsonify

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CURRENT_VERSION = "1.4.8"
GITHUB_REPO = "mwdevru/shopbot-beliyspisok"

from shop_bot.modules import mwshark_api
from shop_bot.bot import handlers
from shop_bot.data_manager.database import (
    get_all_settings, update_setting, get_all_plans,
    create_plan, delete_plan, get_plan_by_id, get_user_count,
    get_total_keys_count, get_total_spent_sum, get_daily_stats_for_charts,
    get_recent_transactions, get_paginated_transactions, get_all_users, get_user_keys,
    ban_user, unban_user, delete_user_keys, get_setting, find_and_complete_ton_transaction,
    get_user, update_key_expiry_days, set_key_expiry_date, get_key_by_id, add_new_key,
    search_users, get_users_with_active_keys, get_users_without_keys, get_banned_users_count,
    get_active_keys_count, get_expired_keys_count, get_transactions_stats, delete_key_by_id,
    reset_trial, delete_user, reset_user_stats, set_referral_balance
)

_bot_controller = None

ALL_SETTINGS_KEYS = [
    "panel_login", "panel_password", "about_text", "terms_url", "privacy_url",
    "android_url", "ios_url", "windows_url", "linux_url",
    "support_user", "support_text", "channel_url", "telegram_bot_token",
    "telegram_bot_username", "admin_telegram_id", "yookassa_shop_id",
    "yookassa_secret_key", "sbp_enabled", "receipt_email", "cryptobot_token",
    "heleket_merchant_id", "heleket_api_key", "domain", "referral_percentage",
    "referral_discount", "force_subscription", "trial_enabled", "trial_duration_days",
    "enable_referrals", "minimum_withdrawal", "support_group_id", "support_bot_token",
    "mwshark_api_key", "platega_merchant_id", "platega_secret_key", "platega_payment_method"
]


def create_webhook_app(bot_controller_instance):
    global _bot_controller
    _bot_controller = bot_controller_instance

    flask_app = Flask(__name__, template_folder='templates', static_folder='static')
    flask_app.config['SECRET_KEY'] = 'lolkek4eburek'

    @flask_app.context_processor
    def inject_globals():
        return {
            'current_year': datetime.utcnow().year,
            'now': datetime.now().isoformat(),
            'app_version': CURRENT_VERSION
        }

    def login_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'logged_in' not in session:
                return redirect(url_for('login_page'))
            return f(*args, **kwargs)
        return decorated_function

    @flask_app.route('/login', methods=['GET', 'POST'])
    def login_page():
        settings = get_all_settings()
        if request.method == 'POST':
            if (request.form.get('username') == settings.get("panel_login") and
                request.form.get('password') == settings.get("panel_password")):
                session['logged_in'] = True
                return redirect(url_for('dashboard_page'))
            flash('Неверный логин или пароль', 'danger')
        return render_template('login.html')

    @flask_app.route('/logout', methods=['POST'])
    @login_required
    def logout_page():
        session.pop('logged_in', None)
        flash('Вы успешно вышли.', 'success')
        return redirect(url_for('login_page'))

    def get_common_template_data():
        bot_status = _bot_controller.get_status()
        settings = get_all_settings()
        required = ['telegram_bot_token', 'telegram_bot_username', 'admin_telegram_id', 'mwshark_api_key']
        all_settings_ok = all(settings.get(key) for key in required)
        return {"bot_status": bot_status, "all_settings_ok": all_settings_ok}

    @flask_app.route('/')
    @login_required
    def index():
        return redirect(url_for('dashboard_page'))

    @flask_app.route('/dashboard')
    @login_required
    def dashboard_page():
        stats = {
            "user_count": get_user_count(),
            "total_keys": get_total_keys_count(),
            "total_spent": get_total_spent_sum(),
            "plans_count": len(get_all_plans())
        }

        page = request.args.get('page', 1, type=int)
        per_page = 8

        transactions, total_transactions = get_paginated_transactions(page=page, per_page=per_page)
        total_pages = ceil(total_transactions / per_page)
        chart_data = get_daily_stats_for_charts(days=30)
        common_data = get_common_template_data()

        api_balance = None
        api_key = get_setting("mwshark_api_key")
        if api_key:
            try:
                loop = current_app.config.get('EVENT_LOOP')
                if loop and loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(mwshark_api.get_api_balance(api_key), loop)
                    api_balance = future.result(timeout=5)
            except Exception as e:
                logger.error(f"Failed to get API balance: {e}")

        return render_template(
            'dashboard.html', stats=stats, chart_data=chart_data, transactions=transactions,
            current_page=page, total_pages=total_pages, api_balance=api_balance, **common_data
        )


    @flask_app.route('/users')
    @login_required
    def users_page():
        search = request.args.get('search', '').strip()
        filter_type = request.args.get('filter', 'all')
        
        if search:
            users = search_users(search)
        elif filter_type == 'active':
            users = get_users_with_active_keys()
        elif filter_type == 'nokeys':
            users = get_users_without_keys()
        else:
            users = get_all_users()
        
        for user in users:
            user['user_keys'] = get_user_keys(user['telegram_id'])
        
        stats = {
            'total': get_user_count(),
            'banned': get_banned_users_count(),
            'with_keys': len(get_users_with_active_keys()),
            'active_keys': get_active_keys_count(),
            'expired_keys': get_expired_keys_count()
        }
        
        return render_template('users.html', users=users, stats=stats, search=search, filter_type=filter_type, **get_common_template_data())

    @flask_app.route('/settings', methods=['GET', 'POST'])
    @login_required
    def settings_page():
        settings_keys = [
            "panel_login", "about_text", "support_text", "terms_url", "privacy_url",
            "android_url", "ios_url", "windows_url", "linux_url",
            "support_user", "channel_url", "telegram_bot_token",
            "telegram_bot_username", "admin_telegram_id", "referral_percentage",
            "referral_discount", "trial_duration_days", "minimum_withdrawal",
            "support_group_id", "support_bot_token", "mwshark_api_key"
        ]
        if request.method == 'POST':
            if 'panel_password' in request.form and request.form.get('panel_password'):
                update_setting('panel_password', request.form.get('panel_password'))

            for checkbox_key in ['force_subscription', 'trial_enabled', 'enable_referrals']:
                values = request.form.getlist(checkbox_key)
                value = values[-1] if values else 'false'
                update_setting(checkbox_key, 'true' if value == 'true' else 'false')

            for key in settings_keys:
                if key in request.form:
                    update_setting(key, request.form.get(key, ''))

            flash('Настройки успешно сохранены!', 'success')
            return redirect(url_for('settings_page'))

        return render_template('settings.html', settings=get_all_settings(), **get_common_template_data())

    @flask_app.route('/plans')
    @login_required
    def plans_page():
        return render_template('plans.html', plans=get_all_plans(), **get_common_template_data())

    @flask_app.route('/payments', methods=['GET', 'POST'])
    @login_required
    def payments_page():
        if request.method == 'POST':
            payment_keys = [
                'yookassa_shop_id', 'yookassa_secret_key', 'receipt_email',
                'cryptobot_token', 'heleket_merchant_id', 'heleket_api_key', 'domain',
                'platega_merchant_id', 'platega_secret_key', 'platega_payment_method'
            ]
            for checkbox_key in ['sbp_enabled']:
                values = request.form.getlist(checkbox_key)
                value = values[-1] if values else 'false'
                update_setting(checkbox_key, 'true' if value == 'true' else 'false')
            for key in payment_keys:
                if key in request.form:
                    update_setting(key, request.form.get(key, ''))
            flash('Настройки платежей сохранены!', 'success')
            return redirect(url_for('payments_page'))
        return render_template('payments.html', settings=get_all_settings(), **get_common_template_data())

    @flask_app.route('/start-shop-bot', methods=['POST'])
    @login_required
    def start_shop_bot_route():
        result = _bot_controller.start_shop_bot()
        flash(result.get('message', 'Error'), 'success' if result.get('status') == 'success' else 'danger')
        return redirect(request.referrer or url_for('dashboard_page'))

    @flask_app.route('/stop-shop-bot', methods=['POST'])
    @login_required
    def stop_shop_bot_route():
        result = _bot_controller.stop_shop_bot()
        flash(result.get('message', 'Error'), 'success' if result.get('status') == 'success' else 'danger')
        return redirect(request.referrer or url_for('dashboard_page'))

    @flask_app.route('/start-support-bot', methods=['POST'])
    @login_required
    def start_support_bot_route():
        result = _bot_controller.start_support_bot()
        flash(result.get('message', 'Error'), 'success' if result.get('status') == 'success' else 'danger')
        return redirect(request.referrer or url_for('dashboard_page'))

    @flask_app.route('/stop-support-bot', methods=['POST'])
    @login_required
    def stop_support_bot_route():
        result = _bot_controller.stop_support_bot()
        flash(result.get('message', 'Error'), 'success' if result.get('status') == 'success' else 'danger')
        return redirect(request.referrer or url_for('dashboard_page'))

    @flask_app.route('/users/ban/<int:user_id>', methods=['POST'])
    @login_required
    def ban_user_route(user_id):
        ban_user(user_id)
        flash(f'Пользователь {user_id} заблокирован.', 'success')
        return redirect(request.referrer or url_for('user_detail_page', user_id=user_id))

    @flask_app.route('/users/unban/<int:user_id>', methods=['POST'])
    @login_required
    def unban_user_route(user_id):
        unban_user(user_id)
        flash(f'Пользователь {user_id} разблокирован.', 'success')
        return redirect(request.referrer or url_for('user_detail_page', user_id=user_id))

    @flask_app.route('/users/revoke/<int:user_id>', methods=['POST'])
    @login_required
    def revoke_keys_route(user_id):
        api_key = get_setting("mwshark_api_key")
        if not api_key:
            delete_user_keys(user_id)
            flash(f"Ключи пользователя {user_id} удалены (локально).", 'success')
            return redirect(url_for('user_detail_page', user_id=user_id))
        
        try:
            loop = current_app.config.get('EVENT_LOOP')
            if loop and loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    mwshark_api.revoke_subscription_for_user(api_key, user_id), loop
                )
                result = future.result(timeout=10)
                
                if result.get('success'):
                    revoke_info = result.get('revoke', {})
                    days_revoked = revoke_info.get('days_revoked', 0)
                    delete_user_keys(user_id)
                    flash(f"Подписка отозвана: {days_revoked} дней. Ключи удалены.", 'success')
                else:
                    error = result.get('error', 'Неизвестная ошибка')
                    if 'not found' in error.lower() or 'no grants' in error.lower():
                        delete_user_keys(user_id)
                        flash(f"Ключи удалены (грантов для отзыва не найдено).", 'success')
                    else:
                        flash(f"Ошибка API: {error}", 'danger')
            else:
                delete_user_keys(user_id)
                flash(f"Ключи удалены (event loop недоступен).", 'warning')
        except Exception as e:
            logger.error(f"Revoke keys error: {e}")
            delete_user_keys(user_id)
            flash(f"Ключи удалены локально. Ошибка API: {e}", 'warning')
        
        return redirect(url_for('user_detail_page', user_id=user_id))

    @flask_app.route('/users/revoke/<int:user_id>/<int:key_id>', methods=['POST'])
    @login_required
    def revoke_single_key_route(user_id, key_id):
        key_data = get_key_by_id(key_id)
        if not key_data or key_data['user_id'] != user_id:
            flash('Ключ не найден.', 'danger')
            return redirect(url_for('user_detail_page', user_id=user_id))
        
        api_key = get_setting("mwshark_api_key")
        
        remaining_keys = [k for k in get_user_keys(user_id) if k['key_id'] != key_id]
        
        if api_key and not remaining_keys:
            try:
                loop = current_app.config.get('EVENT_LOOP')
                if loop and loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        mwshark_api.revoke_subscription_for_user(api_key, user_id), loop
                    )
                    result = future.result(timeout=10)
                    if result.get('success'):
                        flash(f"Подписка отозвана через API.", 'success')
            except Exception as e:
                logger.error(f"Revoke single key API error: {e}")
        
        delete_key_by_id(key_id)
        flash(f"Ключ #{key_id} удалён.", 'success')
        return redirect(url_for('user_detail_page', user_id=user_id))


    @flask_app.route('/users/modify-days/<int:user_id>', methods=['POST'])
    @login_required
    def modify_user_days_route(user_id):
        days = request.form.get('days', type=int)
        key_id = request.form.get('key_id', type=int)
        
        if not days:
            flash('Укажите количество дней.', 'danger')
            return redirect(url_for('users_page'))
        
        api_key = get_setting("mwshark_api_key")
        if not api_key:
            flash('API ключ не настроен.', 'danger')
            return redirect(url_for('users_page'))
        
        try:
            loop = current_app.config.get('EVENT_LOOP')
            if loop and loop.is_running():
                if days > 0:
                    key_data = get_key_by_id(key_id) if key_id else None
                    if not key_data or not key_data.get('subscription_uuid'):
                        flash('UUID подписки не найден.', 'danger')
                        return redirect(url_for('users_page'))
                    
                    future = asyncio.run_coroutine_threadsafe(
                        mwshark_api.extend_subscription_for_user(api_key, key_data['subscription_uuid'], days), loop
                    )
                    result = future.result(timeout=10)
                    if result.get('success'):
                        if key_id:
                            update_key_expiry_days(key_id, days)
                        flash(f'Добавлено {days} дней пользователю {user_id}.', 'success')
                    else:
                        flash(f"Ошибка API: {result.get('error', 'Неизвестная ошибка')}", 'danger')
                else:
                    key_data = get_key_by_id(key_id) if key_id else None
                    if not key_data or not key_data.get('subscription_uuid'):
                        flash('UUID подписки не найден.', 'danger')
                        return redirect(url_for('users_page'))
                    
                    future = asyncio.run_coroutine_threadsafe(
                        mwshark_api.revoke_subscription_for_user(api_key, key_data['subscription_uuid']), loop
                    )
                    result = future.result(timeout=10)
                    if result.get('success'):
                        delete_user_keys(user_id)
                        flash(f'Подписка пользователя {user_id} отозвана.', 'success')
                    else:
                        flash(f"Ошибка API: {result.get('error', 'Неизвестная ошибка')}", 'danger')
        except Exception as e:
            logger.error(f"Modify days error: {e}")
            flash(f'Ошибка: {e}', 'danger')
        
        return redirect(url_for('users_page'))

    @flask_app.route('/users/grant-key/<int:user_id>', methods=['POST'])
    @login_required
    def grant_key_route(user_id):
        days = request.form.get('days', type=int, default=30)
        
        api_key = get_setting("mwshark_api_key")
        if not api_key:
            flash('API ключ не настроен.', 'danger')
            return redirect(url_for('users_page'))
        
        try:
            loop = current_app.config.get('EVENT_LOOP')
            if loop and loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    mwshark_api.create_subscription_for_user(api_key, user_id, days, f"Admin grant for {user_id}"), loop
                )
                result = future.result(timeout=10)
                
                if result.get('success'):
                    subscription = result.get('subscription', {})
                    subscription_uuid = subscription.get('uuid', '')
                    expiry_str = subscription.get('expiry_date', '')
                    expiry_date = datetime.fromisoformat(expiry_str.replace('+00:00', ''))
                    expiry_ms = int(expiry_date.timestamp() * 1000)
                    subscription_link = subscription.get('link', '')
                    
                    add_new_key(user_id, subscription_link, expiry_ms, subscription_uuid)
                    flash(f'Ключ на {days} дней выдан пользователю {user_id}.', 'success')
                else:
                    flash(f"Ошибка API: {result.get('error', 'Неизвестная ошибка')}", 'danger')
        except Exception as e:
            logger.error(f"Grant key error: {e}")
            flash(f'Ошибка: {e}', 'danger')
        
        return redirect(url_for('users_page'))

    @flask_app.route('/users/reset-trial/<int:user_id>', methods=['POST'])
    @login_required
    def reset_trial_route(user_id):
        reset_trial(user_id)
        flash(f'Триал сброшен для {user_id}.', 'success')
        return redirect(url_for('user_detail_page', user_id=user_id))

    @flask_app.route('/users/reset-stats/<int:user_id>', methods=['POST'])
    @login_required
    def reset_stats_route(user_id):
        reset_user_stats(user_id)
        flash(f'Статистика сброшена для {user_id}.', 'success')
        return redirect(url_for('user_detail_page', user_id=user_id))

    @flask_app.route('/users/set-balance/<int:user_id>', methods=['POST'])
    @login_required
    def set_balance_route(user_id):
        balance = request.form.get('balance', type=float, default=0)
        set_referral_balance(user_id, balance)
        flash(f'Баланс установлен: {balance} ₽', 'success')
        return redirect(url_for('user_detail_page', user_id=user_id))

    @flask_app.route('/users/delete/<int:user_id>', methods=['POST'])
    @login_required
    def delete_user_route(user_id):
        api_key = get_setting("mwshark_api_key")
        if api_key:
            try:
                loop = current_app.config.get('EVENT_LOOP')
                if loop and loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        mwshark_api.revoke_subscription_for_user(api_key, user_id), loop
                    )
                    future.result(timeout=10)
            except Exception as e:
                logger.error(f"Revoke before delete error: {e}")
        delete_user(user_id)
        flash(f'Пользователь {user_id} удалён.', 'success')
        return redirect(url_for('users_page'))

    @flask_app.route('/add-plan', methods=['POST'])
    @login_required
    def add_plan_route():
        create_plan(
            plan_name=request.form['plan_name'],
            days=int(request.form['days']),
            price=float(request.form['price'])
        )
        flash(f"Тариф '{request.form['plan_name']}' добавлен.", 'success')
        return redirect(url_for('plans_page'))

    @flask_app.route('/delete-plan/<int:plan_id>', methods=['POST'])
    @login_required
    def delete_plan_route(plan_id):
        delete_plan(plan_id)
        flash("Тариф удален.", 'success')
        return redirect(url_for('plans_page'))

    @flask_app.route('/api-stats')
    @login_required
    def api_stats_page():
        api_key = get_setting("mwshark_api_key")
        if not api_key:
            flash('API ключ не настроен.', 'danger')
            return redirect(url_for('settings_page'))
        
        data = {'balance': None, 'grants': [], 'history': [], 'tariffs': []}
        
        try:
            loop = current_app.config.get('EVENT_LOOP')
            if loop and loop.is_running():
                balance_future = asyncio.run_coroutine_threadsafe(mwshark_api.get_api_balance(api_key), loop)
                grants_future = asyncio.run_coroutine_threadsafe(mwshark_api.get_user_grants(api_key), loop)
                history_future = asyncio.run_coroutine_threadsafe(mwshark_api.get_api_history(api_key), loop)
                tariffs_future = asyncio.run_coroutine_threadsafe(mwshark_api.get_api_tariffs(api_key), loop)
                
                data['balance'] = balance_future.result(timeout=5)
                data['grants'] = grants_future.result(timeout=5).get('grants', [])
                data['history'] = history_future.result(timeout=5).get('purchases', [])
                data['tariffs'] = tariffs_future.result(timeout=5).get('tariffs', [])
        except Exception as e:
            logger.error(f"API stats error: {e}")
            flash(f'Ошибка загрузки данных API: {e}', 'danger')
        
        return render_template('api_stats.html', data=data, **get_common_template_data())

    @flask_app.route('/transactions')
    @login_required
    def transactions_page():
        page = request.args.get('page', 1, type=int)
        per_page = 20
        transactions, total = get_paginated_transactions(page=page, per_page=per_page)
        total_pages = ceil(total / per_page)
        stats = get_transactions_stats()
        return render_template('transactions.html', transactions=transactions, stats=stats,
                               current_page=page, total_pages=total_pages, **get_common_template_data())

    @flask_app.route('/export/users')
    @login_required
    def export_users():
        users = get_all_users()
        output = "telegram_id,username,total_spent,total_months,is_banned,registration_date\n"
        for u in users:
            output += f"{u['telegram_id']},{u.get('username','')},{u.get('total_spent',0)},{u.get('total_months',0)},{u.get('is_banned',0)},{u.get('registration_date','')}\n"
        return output, 200, {'Content-Type': 'text/csv', 'Content-Disposition': 'attachment; filename=users.csv'}

    @flask_app.route('/broadcast', methods=['GET', 'POST'])
    @login_required
    def broadcast_page():
        if request.method == 'POST':
            message_text = request.form.get('message', '').strip()
            if not message_text:
                flash('Введите текст сообщения.', 'danger')
                return redirect(url_for('broadcast_page'))
            
            bot = _bot_controller.get_bot_instance()
            loop = current_app.config.get('EVENT_LOOP')
            
            if not bot or not loop or not loop.is_running():
                flash('Бот не запущен.', 'danger')
                return redirect(url_for('broadcast_page'))
            
            users = get_all_users()
            sent = 0
            failed = 0
            
            async def send_broadcast():
                nonlocal sent, failed
                for user in users:
                    if user.get('is_banned'):
                        continue
                    try:
                        await bot.send_message(user['telegram_id'], message_text, parse_mode='HTML')
                        sent += 1
                        await asyncio.sleep(0.05)
                    except Exception:
                        failed += 1
            
            future = asyncio.run_coroutine_threadsafe(send_broadcast(), loop)
            future.result(timeout=300)
            
            flash(f'Рассылка завершена. Отправлено: {sent}, ошибок: {failed}', 'success')
            return redirect(url_for('broadcast_page'))
        
        return render_template('broadcast.html', user_count=get_user_count(), **get_common_template_data())

    @flask_app.route('/users/message/<int:user_id>', methods=['POST'])
    @login_required
    def send_message_to_user(user_id):
        message_text = request.form.get('message', '').strip()
        if not message_text:
            flash('Введите текст.', 'danger')
            return redirect(url_for('users_page'))
        
        bot = _bot_controller.get_bot_instance()
        loop = current_app.config.get('EVENT_LOOP')
        
        if bot and loop and loop.is_running():
            async def send():
                await bot.send_message(user_id, message_text, parse_mode='HTML')
            try:
                future = asyncio.run_coroutine_threadsafe(send(), loop)
                future.result(timeout=10)
                flash(f'Сообщение отправлено {user_id}.', 'success')
            except Exception as e:
                flash(f'Ошибка: {e}', 'danger')
        else:
            flash('Бот не запущен.', 'danger')
        
        return redirect(request.referrer or url_for('users_page'))

    @flask_app.route('/users/<int:user_id>')
    @login_required
    def user_detail_page(user_id):
        user = get_user(user_id)
        if not user:
            flash('Пользователь не найден.', 'danger')
            return redirect(url_for('users_page'))
        
        user['user_keys'] = get_user_keys(user_id)
        
        api_subscription = None
        api_key = get_setting("mwshark_api_key")
        if api_key:
            try:
                loop = current_app.config.get('EVENT_LOOP')
                if loop and loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        mwshark_api.get_user_subscription(api_key, user_id), loop
                    )
                    result = future.result(timeout=5)
                    if result.get('success'):
                        api_subscription = result.get('subscription')
            except Exception as e:
                logger.error(f"Get subscription error: {e}")
        
        plans = get_all_plans()
        return render_template('user_detail.html', user=user, api_subscription=api_subscription, plans=plans, **get_common_template_data())


    @flask_app.route('/yookassa-webhook', methods=['POST'])
    def yookassa_webhook_handler():
        try:
            event_json = request.json
            if event_json.get("event") == "payment.succeeded":
                metadata = event_json.get("object", {}).get("metadata", {})

                bot = _bot_controller.get_bot_instance()
                payment_processor = handlers.process_successful_payment

                if metadata and bot is not None and payment_processor is not None:
                    loop = current_app.config.get('EVENT_LOOP')
                    if loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(payment_processor(bot, metadata), loop)
                    else:
                        logger.error("YooKassa webhook: Event loop not available!")
            return 'OK', 200
        except Exception as e:
            logger.error(f"YooKassa webhook error: {e}", exc_info=True)
            return 'Error', 500

    def verify_cryptobot_signature(token: str, body: bytes) -> bool:
        signature = request.headers.get('crypto-pay-api-signature')
        if not signature:
            return False
        try:
            secret = hashlib.sha256(token.encode()).digest()
            expected_signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
            return compare_digest(expected_signature, signature)
        except Exception:
            return False

    @flask_app.route('/cryptobot-webhook', methods=['POST'])
    def cryptobot_webhook_handler():
        try:
            cryptobot_token = get_setting("cryptobot_token")
            if not cryptobot_token:
                logger.error("CryptoBot Webhook: Token not configured")
                return 'Error', 500

            raw_body = request.get_data()
            if not verify_cryptobot_signature(cryptobot_token, raw_body):
                logger.warning("CryptoBot Webhook: Invalid signature - request rejected")
                return 'Forbidden', 403

            request_data = request.json

            if request_data and request_data.get('update_type') == 'invoice_paid':
                payload_data = request_data.get('payload', {})
                payload_string = payload_data.get('payload')

                if not payload_string:
                    logger.warning("CryptoBot Webhook: Empty payload.")
                    return 'OK', 200

                parts = payload_string.split(':')
                if len(parts) < 8:
                    logger.error(f"CryptoBot Webhook: Invalid payload: {payload_string}")
                    return 'Error', 400

                metadata = {
                    "user_id": parts[0], "days": parts[1], "price": parts[2],
                    "action": parts[3], "key_id": parts[4], "plan_id": parts[5],
                    "customer_email": parts[6] if parts[6] != 'None' else None,
                    "payment_method": parts[7]
                }

                bot = _bot_controller.get_bot_instance()
                loop = current_app.config.get('EVENT_LOOP')
                payment_processor = handlers.process_successful_payment

                if bot and loop and loop.is_running():
                    asyncio.run_coroutine_threadsafe(payment_processor(bot, metadata), loop)
                else:
                    logger.error("CryptoBot Webhook: Bot or event loop not running.")

            return 'OK', 200

        except Exception as e:
            logger.error(f"CryptoBot webhook error: {e}", exc_info=True)
            return 'Error', 500

    @flask_app.route('/heleket-webhook', methods=['POST'])
    def heleket_webhook_handler():
        try:
            data = request.json
            logger.info(f"Heleket webhook: {data}")

            api_key = get_setting("heleket_api_key")
            if not api_key:
                return 'Error', 500

            sign = data.pop("sign", None)
            if not sign:
                return 'Error', 400

            sorted_data_str = json.dumps(data, sort_keys=True, separators=(",", ":"))
            base64_encoded = base64.b64encode(sorted_data_str.encode()).decode()
            expected_sign = hashlib.md5(f"{base64_encoded}{api_key}".encode()).hexdigest()

            if not compare_digest(expected_sign, sign):
                logger.warning("Heleket webhook: Invalid signature.")
                return 'Forbidden', 403

            if data.get('status') in ["paid", "paid_over"]:
                metadata_str = data.get('description')
                if not metadata_str:
                    return 'Error', 400

                metadata = json.loads(metadata_str)

                bot = _bot_controller.get_bot_instance()
                loop = current_app.config.get('EVENT_LOOP')
                payment_processor = handlers.process_successful_payment

                if bot and loop and loop.is_running():
                    asyncio.run_coroutine_threadsafe(payment_processor(bot, metadata), loop)

            return 'OK', 200
        except Exception as e:
            logger.error(f"Heleket webhook error: {e}", exc_info=True)
            return 'Error', 500

    @flask_app.route('/ton-webhook', methods=['POST'])
    def ton_webhook_handler():
        try:
            data = request.json
            logger.info(f"TonAPI webhook: {data}")

            if 'tx_id' in data:
                for tx in data.get('in_progress_txs', []) + data.get('txs', []):
                    in_msg = tx.get('in_msg')
                    if in_msg and in_msg.get('decoded_comment'):
                        payment_id = in_msg['decoded_comment']
                        amount_nano = int(in_msg.get('value', 0))
                        amount_ton = float(amount_nano / 1_000_000_000)

                        metadata = find_and_complete_ton_transaction(payment_id, amount_ton)

                        if metadata:
                            logger.info(f"TON Payment successful: {payment_id}")
                            bot = _bot_controller.get_bot_instance()
                            loop = current_app.config.get('EVENT_LOOP')
                            payment_processor = handlers.process_successful_payment

                            if bot and loop and loop.is_running():
                                asyncio.run_coroutine_threadsafe(payment_processor(bot, metadata), loop)

            return 'OK', 200
        except Exception as e:
            logger.error(f"TON webhook error: {e}", exc_info=True)
            return 'Error', 500

    @flask_app.route('/platega-webhook', methods=['POST'])
    def platega_webhook_handler():
        try:
            allowed_ips = ['159.89.29.214']
            client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            if client_ip:
                client_ip = client_ip.split(',')[0].strip()
            
            if client_ip not in allowed_ips:
                logger.warning(f"Platega webhook: Unauthorized IP {client_ip}")
                return 'Forbidden', 403
            
            data = request.json
            logger.info(f"Platega webhook: {data}")

            merchant_id = get_setting("platega_merchant_id")
            secret_key = get_setting("platega_secret_key")

            req_merchant = request.headers.get('X-MerchantId')
            req_secret = request.headers.get('X-Secret')

            if not merchant_id or not secret_key:
                return 'Error', 500

            if req_merchant != merchant_id or req_secret != secret_key:
                logger.warning("Platega webhook: Invalid credentials")
                return 'Forbidden', 403

            status = data.get('status')
            transaction_id = data.get('id') or data.get('transactionId')

            if status == 'CONFIRMED' and transaction_id:
                from shop_bot.data_manager.database import get_pending_platega_transaction, delete_pending_platega_transaction
                metadata = get_pending_platega_transaction(transaction_id)

                if metadata:
                    delete_pending_platega_transaction(transaction_id)
                    bot = _bot_controller.get_bot_instance()
                    loop = current_app.config.get('EVENT_LOOP')
                    payment_processor = handlers.process_successful_payment

                    if bot and loop and loop.is_running():
                        asyncio.run_coroutine_threadsafe(payment_processor(bot, metadata), loop)
                    logger.info(f"Platega payment confirmed: {transaction_id}")

            return 'OK', 200
        except Exception as e:
            logger.error(f"Platega webhook error: {e}", exc_info=True)
            return 'Error', 500

    @flask_app.route('/api/check-update')
    @login_required
    def check_update_api():
        try:
            import urllib.request
            import urllib.error
            
            local_commit = None
            for git_path in ['/app', '.', os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))]:
                try:
                    result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=git_path, capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        local_commit = result.stdout.strip()[:7]
                        break
                except:
                    continue
            
            url = f"https://api.github.com/repos/{GITHUB_REPO}/commits/main"
            req = urllib.request.Request(url, headers={'User-Agent': 'ShopBot', 'Accept': 'application/vnd.github.v3+json'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                remote_commit = data.get('sha', '')[:7]
                commit_message = data.get('commit', {}).get('message', '').split('\n')[0]
                commit_date = data.get('commit', {}).get('committer', {}).get('date', '')
                
                has_update = local_commit != remote_commit if local_commit else True
                
                return jsonify({
                    'current': CURRENT_VERSION,
                    'local_commit': local_commit or 'unknown',
                    'remote_commit': remote_commit,
                    'has_update': has_update,
                    'changelog': commit_message,
                    'commit_date': commit_date,
                    'url': f'https://github.com/{GITHUB_REPO}/commits/main'
                })
        except urllib.error.HTTPError as e:
            return jsonify({'error': str(e), 'current': CURRENT_VERSION, 'has_update': False})
        except Exception as e:
            logger.error(f"Check update error: {e}")
            return jsonify({'error': str(e), 'current': CURRENT_VERSION, 'has_update': False})

    @flask_app.route('/api/changelog')
    @login_required
    def get_changelog_api():
        try:
            import urllib.request
            url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/CHANGELOG.md"
            req = urllib.request.Request(url, headers={'User-Agent': 'ShopBot'})
            with urllib.request.urlopen(req, timeout=5) as response:
                content = response.read().decode('utf-8')
                return jsonify({'success': True, 'content': content})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})

    @flask_app.route('/api/server-info')
    @login_required
    def server_info_api():
        try:
            cpu_percent = psutil.cpu_percent(interval=0.5)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            boot_time = datetime.fromtimestamp(psutil.boot_time())
            uptime = datetime.now() - boot_time
            
            uptime_str = f"{uptime.days}д {uptime.seconds // 3600}ч {(uptime.seconds % 3600) // 60}м"
            
            return jsonify({
                'success': True,
                'hostname': platform.node(),
                'os': f"{platform.system()} {platform.release()}",
                'python': platform.python_version(),
                'cpu_percent': cpu_percent,
                'cpu_count': psutil.cpu_count(),
                'memory_total': round(memory.total / (1024**3), 2),
                'memory_used': round(memory.used / (1024**3), 2),
                'memory_percent': memory.percent,
                'disk_total': round(disk.total / (1024**3), 2),
                'disk_used': round(disk.used / (1024**3), 2),
                'disk_percent': disk.percent,
                'uptime': uptime_str
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})

    @flask_app.route('/updates')
    @login_required
    def updates_page():
        return render_template('updates.html', current_version=CURRENT_VERSION, **get_common_template_data())

    @flask_app.route('/api/do-update', methods=['POST'])
    @login_required
    def do_update_api():
        try:
            result = subprocess.run(
                ['git', 'pull', 'origin', 'main'],
                cwd='/app',
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                return jsonify({
                    'success': True,
                    'message': 'Обновление загружено. Перезапустите контейнер.',
                    'output': result.stdout
                })
            else:
                return jsonify({
                    'success': False,
                    'message': 'Ошибка git pull',
                    'error': result.stderr
                }), 500
        except subprocess.TimeoutExpired:
            return jsonify({'success': False, 'message': 'Таймаут операции'}), 500
        except Exception as e:
            logger.error(f"Update error: {e}")
            return jsonify({'success': False, 'message': str(e)}), 500

    return flask_app

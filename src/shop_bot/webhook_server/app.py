import os
import logging
import asyncio
import json
import hashlib
import base64
from hmac import compare_digest
from datetime import datetime
from functools import wraps
from math import ceil
from flask import Flask, request, render_template, redirect, url_for, flash, session, current_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from shop_bot.modules import mwshark_api
from shop_bot.bot import handlers 
from shop_bot.data_manager.database import (
    get_all_settings, update_setting, get_all_plans,
    create_plan, delete_plan, get_plan_by_id, get_user_count,
    get_total_keys_count, get_total_spent_sum, get_daily_stats_for_charts,
    get_recent_transactions, get_paginated_transactions, get_all_users, get_user_keys,
    ban_user, unban_user, delete_user_keys, get_setting, find_and_complete_ton_transaction
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
    "mwshark_api_key"
]

def create_webhook_app(bot_controller_instance):
    global _bot_controller
    _bot_controller = bot_controller_instance

    app_file_path = os.path.abspath(__file__)
    app_dir = os.path.dirname(app_file_path)
    
    flask_app = Flask(
        __name__,
        template_folder='templates',
        static_folder='static'
    )
    
    flask_app.config['SECRET_KEY'] = 'lolkek4eburek'

    @flask_app.context_processor
    def inject_current_year():
        return {'current_year': datetime.utcnow().year}

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
            if request.form.get('username') == settings.get("panel_login") and \
               request.form.get('password') == settings.get("panel_password"):
                session['logged_in'] = True
                return redirect(url_for('dashboard_page'))
            else:
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
        required_for_start = ['telegram_bot_token', 'telegram_bot_username', 'admin_telegram_id', 'mwshark_api_key']
        all_settings_ok = all(settings.get(key) for key in required_for_start)
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
        
        # Get API balance
        api_balance = None
        api_key = get_setting("mwshark_api_key")
        if api_key:
            try:
                loop = current_app.config.get('EVENT_LOOP')
                if loop and loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        mwshark_api.get_api_balance(api_key), loop
                    )
                    api_balance = future.result(timeout=5)
            except Exception as e:
                logger.error(f"Failed to get API balance: {e}")
        
        return render_template(
            'dashboard.html',
            stats=stats,
            chart_data=chart_data,
            transactions=transactions,
            current_page=page,
            total_pages=total_pages,
            api_balance=api_balance,
            **common_data
        )

    @flask_app.route('/users')
    @login_required
    def users_page():
        users = get_all_users()
        for user in users:
            user['user_keys'] = get_user_keys(user['telegram_id'])
        
        common_data = get_common_template_data()
        return render_template('users.html', users=users, **common_data)

    @flask_app.route('/settings', methods=['GET', 'POST'])
    @login_required
    def settings_page():
        if request.method == 'POST':
            if 'panel_password' in request.form and request.form.get('panel_password'):
                update_setting('panel_password', request.form.get('panel_password'))

            for checkbox_key in ['force_subscription', 'sbp_enabled', 'trial_enabled', 'enable_referrals']:
                values = request.form.getlist(checkbox_key)
                value = values[-1] if values else 'false'
                update_setting(checkbox_key, 'true' if value == 'true' else 'false')

            for key in ALL_SETTINGS_KEYS:
                if key in ['panel_password', 'force_subscription', 'sbp_enabled', 'trial_enabled', 'enable_referrals']:
                    continue
                update_setting(key, request.form.get(key, ''))

            flash('Настройки успешно сохранены!', 'success')
            return redirect(url_for('settings_page'))

        current_settings = get_all_settings()
        plans = get_all_plans()
        
        common_data = get_common_template_data()
        return render_template('settings.html', settings=current_settings, plans=plans, **common_data)

    @flask_app.route('/start-shop-bot', methods=['POST'])
    @login_required
    def start_shop_bot_route():
        result = _bot_controller.start_shop_bot()
        flash(result.get('message', 'An error occurred.'), 'success' if result.get('status') == 'success' else 'danger')
        return redirect(request.referrer or url_for('dashboard_page'))

    @flask_app.route('/stop-shop-bot', methods=['POST'])
    @login_required
    def stop_shop_bot_route():
        result = _bot_controller.stop_shop_bot()
        flash(result.get('message', 'An error occurred.'), 'success' if result.get('status') == 'success' else 'danger')
        return redirect(request.referrer or url_for('dashboard_page'))

    @flask_app.route('/start-support-bot', methods=['POST'])
    @login_required
    def start_support_bot_route():
        result = _bot_controller.start_support_bot()
        flash(result.get('message', 'An error occurred.'), 'success' if result.get('status') == 'success' else 'danger')
        return redirect(request.referrer or url_for('dashboard_page'))

    @flask_app.route('/stop-support-bot', methods=['POST'])
    @login_required
    def stop_support_bot_route():
        result = _bot_controller.stop_support_bot()
        flash(result.get('message', 'An error occurred.'), 'success' if result.get('status') == 'success' else 'danger')
        return redirect(request.referrer or url_for('dashboard_page'))

    @flask_app.route('/users/ban/<int:user_id>', methods=['POST'])
    @login_required
    def ban_user_route(user_id):
        ban_user(user_id)
        flash(f'Пользователь {user_id} был заблокирован.', 'success')
        return redirect(url_for('users_page'))

    @flask_app.route('/users/unban/<int:user_id>', methods=['POST'])
    @login_required
    def unban_user_route(user_id):
        unban_user(user_id)
        flash(f'Пользователь {user_id} был разблокирован.', 'success')
        return redirect(url_for('users_page'))

    @flask_app.route('/users/revoke/<int:user_id>', methods=['POST'])
    @login_required
    def revoke_keys_route(user_id):
        delete_user_keys(user_id)
        flash(f"Все ключи для пользователя {user_id} были удалены из базы.", 'success')
        return redirect(url_for('users_page'))

    @flask_app.route('/add-plan', methods=['POST'])
    @login_required
    def add_plan_route():
        create_plan(
            plan_name=request.form['plan_name'],
            days=int(request.form['days']),
            price=float(request.form['price'])
        )
        flash(f"Новый тариф '{request.form['plan_name']}' добавлен.", 'success')
        return redirect(url_for('settings_page'))

    @flask_app.route('/delete-plan/<int:plan_id>', methods=['POST'])
    @login_required
    def delete_plan_route(plan_id):
        delete_plan(plan_id)
        flash("Тариф успешно удален.", 'success')
        return redirect(url_for('settings_page'))

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
                        logger.error("YooKassa webhook: Event loop is not available!")
            return 'OK', 200
        except Exception as e:
            logger.error(f"Error in yookassa webhook handler: {e}", exc_info=True)
            return 'Error', 500
        
    @flask_app.route('/cryptobot-webhook', methods=['POST'])
    def cryptobot_webhook_handler():
        try:
            request_data = request.json
            
            if request_data and request_data.get('update_type') == 'invoice_paid':
                payload_data = request_data.get('payload', {})
                payload_string = payload_data.get('payload')
                
                if not payload_string:
                    logger.warning("CryptoBot Webhook: Received paid invoice but payload was empty.")
                    return 'OK', 200

                parts = payload_string.split(':')
                if len(parts) < 8:
                    logger.error(f"cryptobot Webhook: Invalid payload format received: {payload_string}")
                    return 'Error', 400

                metadata = {
                    "user_id": parts[0],
                    "days": parts[1],
                    "price": parts[2],
                    "action": parts[3],
                    "key_id": parts[4],
                    "plan_id": parts[5],
                    "customer_email": parts[6] if parts[6] != 'None' else None,
                    "payment_method": parts[7]
                }
                
                bot = _bot_controller.get_bot_instance()
                loop = current_app.config.get('EVENT_LOOP')
                payment_processor = handlers.process_successful_payment

                if bot and loop and loop.is_running():
                    asyncio.run_coroutine_threadsafe(payment_processor(bot, metadata), loop)
                else:
                    logger.error("cryptobot Webhook: Could not process payment because bot or event loop is not running.")

            return 'OK', 200
            
        except Exception as e:
            logger.error(f"Error in cryptobot webhook handler: {e}", exc_info=True)
            return 'Error', 500

    @flask_app.route('/heleket-webhook', methods=['POST'])
    def heleket_webhook_handler():
        try:
            data = request.json
            logger.info(f"Received Heleket webhook: {data}")

            api_key = get_setting("heleket_api_key")
            if not api_key:
                return 'Error', 500

            sign = data.pop("sign", None)
            if not sign:
                return 'Error', 400
                
            sorted_data_str = json.dumps(data, sort_keys=True, separators=(",", ":"))
            base64_encoded = base64.b64encode(sorted_data_str.encode()).decode()
            raw_string = f"{base64_encoded}{api_key}"
            expected_sign = hashlib.md5(raw_string.encode()).hexdigest()

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
            logger.error(f"Error in heleket webhook handler: {e}", exc_info=True)
            return 'Error', 500
        
    @flask_app.route('/ton-webhook', methods=['POST'])
    def ton_webhook_handler():
        try:
            data = request.json
            logger.info(f"Received TonAPI webhook: {data}")

            if 'tx_id' in data:
                for tx in data.get('in_progress_txs', []) + data.get('txs', []):
                    in_msg = tx.get('in_msg')
                    if in_msg and in_msg.get('decoded_comment'):
                        payment_id = in_msg['decoded_comment']
                        amount_nano = int(in_msg.get('value', 0))
                        amount_ton = float(amount_nano / 1_000_000_000)

                        metadata = find_and_complete_ton_transaction(payment_id, amount_ton)
                        
                        if metadata:
                            logger.info(f"TON Payment successful for payment_id: {payment_id}")
                            bot = _bot_controller.get_bot_instance()
                            loop = current_app.config.get('EVENT_LOOP')
                            payment_processor = handlers.process_successful_payment

                            if bot and loop and loop.is_running():
                                asyncio.run_coroutine_threadsafe(payment_processor(bot, metadata), loop)
            
            return 'OK', 200
        except Exception as e:
            logger.error(f"Error in ton webhook handler: {e}", exc_info=True)
            return 'Error', 500

    return flask_app

import sqlite3
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path("/app/project")
DB_FILE = PROJECT_ROOT / "users.db"


def initialize_db():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY, username TEXT, total_spent REAL DEFAULT 0,
                    total_months INTEGER DEFAULT 0, trial_used BOOLEAN DEFAULT 0,
                    agreed_to_terms BOOLEAN DEFAULT 0,
                    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_banned BOOLEAN DEFAULT 0,
                    referred_by INTEGER,
                    referral_balance REAL DEFAULT 0,
                    referral_balance_all REAL DEFAULT 0
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS vpn_keys (
                    key_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    subscription_link TEXT,
                    expiry_date TIMESTAMP,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    username TEXT,
                    transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payment_id TEXT UNIQUE NOT NULL,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    amount_rub REAL NOT NULL,
                    amount_currency REAL,
                    currency_name TEXT,
                    payment_method TEXT,
                    metadata TEXT,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS support_threads (
                    user_id INTEGER PRIMARY KEY,
                    thread_id INTEGER NOT NULL
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS plans (
                    plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_name TEXT NOT NULL,
                    days INTEGER NOT NULL,
                    price REAL NOT NULL
                )
            ''')
            default_settings = {
                "panel_login": "admin",
                "panel_password": "admin",
                "about_text": None,
                "terms_url": None,
                "privacy_url": None,
                "support_user": None,
                "support_text": None,
                "channel_url": None,
                "force_subscription": "true",
                "receipt_email": "example@example.com",
                "telegram_bot_token": None,
                "support_bot_token": None,
                "telegram_bot_username": None,
                "trial_enabled": "true",
                "trial_duration_days": "3",
                "enable_referrals": "true",
                "referral_percentage": "10",
                "referral_discount": "5",
                "minimum_withdrawal": "100",
                "support_group_id": None,
                "admin_telegram_id": None,
                "yookassa_shop_id": None,
                "yookassa_secret_key": None,
                "sbp_enabled": "false",
                "cryptobot_token": None,
                "heleket_merchant_id": None,
                "heleket_api_key": None,
                "domain": None,
                "ton_wallet_address": None,
                "tonapi_key": None,
                "android_url": "https://telegra.ph/Instrukciya-Android-11-09",
                "windows_url": "https://telegra.ph/Instrukciya-Windows-11-09",
                "ios_url": "https://telegra.ph/Instrukcii-ios-11-09",
                "linux_url": "https://telegra.ph/Instrukciya-Linux-11-09",
                "mwshark_api_key": None,
            }
            run_migration()
            for key, value in default_settings.items():
                cursor.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
            logging.info("Database initialized successfully.")
    except sqlite3.Error as e:
        logging.error(f"Database error on initialization: {e}")


def run_migration():
    if not DB_FILE.exists():
        logging.error("Users.db database file was not found.")
        return

    logging.info(f"Starting the migration of the database: {DB_FILE}")

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        logging.info("Migrating table 'users'...")
        cursor.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]

        migrations = [
            ('referred_by', "ALTER TABLE users ADD COLUMN referred_by INTEGER"),
            ('referral_balance', "ALTER TABLE users ADD COLUMN referral_balance REAL DEFAULT 0"),
            ('referral_balance_all', "ALTER TABLE users ADD COLUMN referral_balance_all REAL DEFAULT 0")
        ]

        for col_name, sql in migrations:
            if col_name not in columns:
                cursor.execute(sql)
                logging.info(f"Column '{col_name}' added.")

        logging.info("Migrating table 'transactions'...")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'")
        table_exists = cursor.fetchone()

        if table_exists:
            cursor.execute("PRAGMA table_info(transactions)")
            trans_columns = [row[1] for row in cursor.fetchall()]

            if not all(col in trans_columns for col in ['payment_id', 'status', 'username']):
                backup_name = f"transactions_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                logging.warning(f"Old structure found. Renaming to '{backup_name}'...")
                cursor.execute(f"ALTER TABLE transactions RENAME TO {backup_name}")
                create_new_transactions_table(cursor)
        else:
            create_new_transactions_table(cursor)

        conn.commit()
        conn.close()
        logging.info("Database migration completed.")

    except sqlite3.Error as e:
        logging.error(f"Migration error: {e}")


def create_new_transactions_table(cursor: sqlite3.Cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            username TEXT,
            transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_id TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            amount_rub REAL NOT NULL,
            amount_currency REAL,
            currency_name TEXT,
            payment_method TEXT,
            metadata TEXT,
            created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')


def create_plan(plan_name: str, days: int, price: float):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO plans (plan_name, days, price) VALUES (?, ?, ?)", (plan_name, days, price))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Failed to create plan: {e}")


def delete_plan(plan_id: int):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM plans WHERE plan_id = ?", (plan_id,))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Failed to delete plan {plan_id}: {e}")


def get_all_plans() -> list[dict]:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM plans ORDER BY days")
            return [dict(plan) for plan in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"Failed to get plans: {e}")
        return []


def get_plan_by_id(plan_id: int) -> dict | None:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM plans WHERE plan_id = ?", (plan_id,))
            plan = cursor.fetchone()
            return dict(plan) if plan else None
    except sqlite3.Error as e:
        logging.error(f"Failed to get plan {plan_id}: {e}")
        return None


def get_all_keys() -> list[dict]:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vpn_keys")
            return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"Failed to get keys: {e}")
        return []


def get_setting(key: str) -> str | None:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
            result = cursor.fetchone()
            return result[0] if result else None
    except sqlite3.Error as e:
        logging.error(f"Failed to get setting '{key}': {e}")
        return None


def get_all_settings() -> dict:
    settings = {}
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM bot_settings")
            for row in cursor.fetchall():
                settings[row['key']] = row['value']
    except sqlite3.Error as e:
        logging.error(f"Failed to get settings: {e}")
    return settings


def update_setting(key: str, value: str):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Failed to update setting '{key}': {e}")


def register_user_if_not_exists(telegram_id: int, username: str, referrer_id):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT telegram_id FROM users WHERE telegram_id = ?", (telegram_id,))
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO users (telegram_id, username, registration_date, referred_by) VALUES (?, ?, ?, ?)",
                    (telegram_id, username, datetime.now(), referrer_id)
                )
            else:
                cursor.execute("UPDATE users SET username = ? WHERE telegram_id = ?", (username, telegram_id))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Failed to register user {telegram_id}: {e}")


def add_to_referral_balance(user_id: int, amount: float):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET referral_balance = referral_balance + ? WHERE telegram_id = ?", (amount, user_id))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Failed to add referral balance for {user_id}: {e}")


def set_referral_balance(user_id: int, value: float):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET referral_balance = ? WHERE telegram_id = ?", (value, user_id))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Failed to set referral balance for {user_id}: {e}")


def set_referral_balance_all(user_id: int, value: float):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET referral_balance_all = ? WHERE telegram_id = ?", (value, user_id))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Failed to set total referral balance for {user_id}: {e}")


def get_referral_balance(user_id: int) -> float:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT referral_balance FROM users WHERE telegram_id = ?", (user_id,))
            result = cursor.fetchone()
            return result[0] if result else 0.0
    except sqlite3.Error as e:
        logging.error(f"Failed to get referral balance for {user_id}: {e}")
        return 0.0


def get_referral_count(user_id: int) -> int:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,))
            return cursor.fetchone()[0] or 0
    except sqlite3.Error as e:
        logging.error(f"Failed to get referral count for {user_id}: {e}")
        return 0


def get_user(telegram_id: int):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            user_data = cursor.fetchone()
            return dict(user_data) if user_data else None
    except sqlite3.Error as e:
        logging.error(f"Failed to get user {telegram_id}: {e}")
        return None


def set_terms_agreed(telegram_id: int):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET agreed_to_terms = 1 WHERE telegram_id = ?", (telegram_id,))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Failed to set terms agreed for {telegram_id}: {e}")


def update_user_stats(telegram_id: int, amount_spent: float, months_purchased: int):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET total_spent = total_spent + ?, total_months = total_months + ? WHERE telegram_id = ?",
                (amount_spent, months_purchased, telegram_id)
            )
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Failed to update stats for {telegram_id}: {e}")


def get_user_count() -> int:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            return cursor.fetchone()[0] or 0
    except sqlite3.Error as e:
        logging.error(f"Failed to get user count: {e}")
        return 0


def get_total_keys_count() -> int:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM vpn_keys")
            return cursor.fetchone()[0] or 0
    except sqlite3.Error as e:
        logging.error(f"Failed to get keys count: {e}")
        return 0


def get_total_spent_sum() -> float:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(total_spent) FROM users")
            return cursor.fetchone()[0] or 0.0
    except sqlite3.Error as e:
        logging.error(f"Failed to get total spent: {e}")
        return 0.0


def create_pending_transaction(payment_id: str, user_id: int, amount_rub: float, metadata: dict) -> int:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO transactions (payment_id, user_id, status, amount_rub, metadata) VALUES (?, ?, ?, ?, ?)",
                (payment_id, user_id, 'pending', amount_rub, json.dumps(metadata))
            )
            conn.commit()
            return cursor.lastrowid
    except sqlite3.Error as e:
        logging.error(f"Failed to create pending transaction: {e}")
        return 0


def find_and_complete_ton_transaction(payment_id: str, amount_ton: float) -> dict | None:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM transactions WHERE payment_id = ? AND status = 'pending'", (payment_id,))
            transaction = cursor.fetchone()
            if not transaction:
                logger.warning(f"TON Webhook: Unknown payment_id: {payment_id}")
                return None

            cursor.execute(
                "UPDATE transactions SET status = 'paid', amount_currency = ?, currency_name = 'TON', payment_method = 'TON' WHERE payment_id = ?",
                (amount_ton, payment_id)
            )
            conn.commit()

            return json.loads(transaction['metadata'])
    except sqlite3.Error as e:
        logging.error(f"Failed to complete TON transaction {payment_id}: {e}")
        return None


def log_transaction(username: str, transaction_id: str | None, payment_id: str | None, user_id: int, status: str,
                    amount_rub: float, amount_currency: float | None, currency_name: str | None,
                    payment_method: str, metadata: str):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO transactions
                   (username, transaction_id, payment_id, user_id, status, amount_rub, amount_currency, currency_name, payment_method, metadata, created_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (username, transaction_id, payment_id, user_id, status, amount_rub, amount_currency, currency_name, payment_method, metadata, datetime.now())
            )
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Failed to log transaction for {user_id}: {e}")


def get_paginated_transactions(page: int = 1, per_page: int = 15) -> tuple[list[dict], int]:
    offset = (page - 1) * per_page
    transactions = []
    total = 0
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM transactions")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT * FROM transactions ORDER BY created_date DESC LIMIT ? OFFSET ?", (per_page, offset))

            for row in cursor.fetchall():
                transaction_dict = dict(row)
                metadata_str = transaction_dict.get('metadata')
                if metadata_str:
                    try:
                        metadata = json.loads(metadata_str)
                        transaction_dict['host_name'] = metadata.get('host_name', 'N/A')
                        transaction_dict['plan_name'] = metadata.get('plan_name', 'N/A')
                    except json.JSONDecodeError:
                        transaction_dict['host_name'] = 'Error'
                        transaction_dict['plan_name'] = 'Error'
                else:
                    transaction_dict['host_name'] = 'N/A'
                    transaction_dict['plan_name'] = 'N/A'
                transactions.append(transaction_dict)

    except sqlite3.Error as e:
        logging.error(f"Failed to get transactions: {e}")

    return transactions, total


def set_trial_used(telegram_id: int):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET trial_used = 1 WHERE telegram_id = ?", (telegram_id,))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Failed to set trial used for {telegram_id}: {e}")


def add_new_key(user_id: int, subscription_link: str, expiry_timestamp_ms: int):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            expiry_date = datetime.fromtimestamp(expiry_timestamp_ms / 1000)
            cursor.execute(
                "INSERT INTO vpn_keys (user_id, subscription_link, expiry_date) VALUES (?, ?, ?)",
                (user_id, subscription_link, expiry_date)
            )
            new_key_id = cursor.lastrowid
            conn.commit()
            return new_key_id
    except sqlite3.Error as e:
        logging.error(f"Failed to add key for {user_id}: {e}")
        return None


def delete_key_by_id(key_id: int):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM vpn_keys WHERE key_id = ?", (key_id,))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Failed to delete key {key_id}: {e}")


def get_user_keys(user_id: int):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vpn_keys WHERE user_id = ? ORDER BY key_id", (user_id,))
            return [dict(key) for key in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"Failed to get keys for {user_id}: {e}")
        return []


def get_key_by_id(key_id: int):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vpn_keys WHERE key_id = ?", (key_id,))
            key_data = cursor.fetchone()
            return dict(key_data) if key_data else None
    except sqlite3.Error as e:
        logging.error(f"Failed to get key {key_id}: {e}")
        return None


def update_key_info(key_id: int, subscription_link: str, new_expiry_ms: int):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            expiry_date = datetime.fromtimestamp(new_expiry_ms / 1000)
            cursor.execute("UPDATE vpn_keys SET subscription_link = ?, expiry_date = ? WHERE key_id = ?",
                           (subscription_link, expiry_date, key_id))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Failed to update key {key_id}: {e}")


def get_next_key_number(user_id: int) -> int:
    return len(get_user_keys(user_id)) + 1


def get_all_vpn_users():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT user_id FROM vpn_keys")
            return [dict(user) for user in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"Failed to get vpn users: {e}")
        return []


def get_daily_stats_for_charts(days: int = 30) -> dict:
    stats = {'users': {}, 'keys': {}}
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT date(registration_date) as day, COUNT(*)
                FROM users WHERE registration_date >= date('now', ?)
                GROUP BY day ORDER BY day
            """, (f'-{days} days',))
            for row in cursor.fetchall():
                stats['users'][row[0]] = row[1]

            cursor.execute("""
                SELECT date(created_date) as day, COUNT(*)
                FROM vpn_keys WHERE created_date >= date('now', ?)
                GROUP BY day ORDER BY day
            """, (f'-{days} days',))
            for row in cursor.fetchall():
                stats['keys'][row[0]] = row[1]
    except sqlite3.Error as e:
        logging.error(f"Failed to get chart stats: {e}")
    return stats


def get_recent_transactions(limit: int = 15) -> list[dict]:
    transactions = []
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT k.key_id, k.host_name, k.created_date, u.telegram_id, u.username
                FROM vpn_keys k JOIN users u ON k.user_id = u.telegram_id
                ORDER BY k.created_date DESC LIMIT ?
            """, (limit,))
            transactions = [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"Failed to get recent transactions: {e}")
    return transactions


def add_support_thread(user_id: int, thread_id: int):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO support_threads (user_id, thread_id) VALUES (?, ?)", (user_id, thread_id))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Failed to add support thread for {user_id}: {e}")


def get_support_thread_id(user_id: int) -> int | None:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT thread_id FROM support_threads WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            return result[0] if result else None
    except sqlite3.Error as e:
        logging.error(f"Failed to get support thread for {user_id}: {e}")
        return None


def get_user_id_by_thread(thread_id: int) -> int | None:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM support_threads WHERE thread_id = ?", (thread_id,))
            result = cursor.fetchone()
            return result[0] if result else None
    except sqlite3.Error as e:
        logging.error(f"Failed to get user for thread {thread_id}: {e}")
        return None


def get_latest_transaction(user_id: int) -> dict | None:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transactions WHERE user_id = ? ORDER BY created_date DESC LIMIT 1", (user_id,))
            transaction = cursor.fetchone()
            return dict(transaction) if transaction else None
    except sqlite3.Error as e:
        logging.error(f"Failed to get latest transaction for {user_id}: {e}")
        return None


def get_all_users() -> list[dict]:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users ORDER BY registration_date DESC")
            return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"Failed to get users: {e}")
        return []


def ban_user(telegram_id: int):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_banned = 1 WHERE telegram_id = ?", (telegram_id,))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Failed to ban user {telegram_id}: {e}")


def unban_user(telegram_id: int):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_banned = 0 WHERE telegram_id = ?", (telegram_id,))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Failed to unban user {telegram_id}: {e}")


def delete_user_keys(user_id: int):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM vpn_keys WHERE user_id = ?", (user_id,))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Failed to delete keys for {user_id}: {e}")


def update_key_expiry_days(key_id: int, days_delta: int):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT expiry_date FROM vpn_keys WHERE key_id = ?", (key_id,))
            result = cursor.fetchone()
            if result:
                current_expiry = datetime.fromisoformat(result[0])
                new_expiry = current_expiry + timedelta(days=days_delta)
                cursor.execute("UPDATE vpn_keys SET expiry_date = ? WHERE key_id = ?", (new_expiry, key_id))
                conn.commit()
                return True
    except sqlite3.Error as e:
        logging.error(f"Failed to update key expiry for {key_id}: {e}")
    return False


def set_key_expiry_date(key_id: int, new_expiry: datetime):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE vpn_keys SET expiry_date = ? WHERE key_id = ?", (new_expiry, key_id))
            conn.commit()
            return True
    except sqlite3.Error as e:
        logging.error(f"Failed to set key expiry for {key_id}: {e}")
    return False


def search_users(query: str) -> list[dict]:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            search_pattern = f"%{query}%"
            cursor.execute("""
                SELECT * FROM users 
                WHERE username LIKE ? OR CAST(telegram_id AS TEXT) LIKE ?
                ORDER BY registration_date DESC
            """, (search_pattern, search_pattern))
            return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"Search users error: {e}")
        return []


def get_users_with_active_keys() -> list[dict]:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT u.* FROM users u
                INNER JOIN vpn_keys k ON u.telegram_id = k.user_id
                WHERE k.expiry_date > datetime('now')
                ORDER BY u.registration_date DESC
            """)
            return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"Get active users error: {e}")
        return []


def get_users_without_keys() -> list[dict]:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.* FROM users u
                LEFT JOIN vpn_keys k ON u.telegram_id = k.user_id
                WHERE k.key_id IS NULL
                ORDER BY u.registration_date DESC
            """)
            return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"Get users without keys error: {e}")
        return []


def get_banned_users_count() -> int:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
            return cursor.fetchone()[0] or 0
    except sqlite3.Error as e:
        logging.error(f"Get banned count error: {e}")
        return 0


def get_active_keys_count() -> int:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM vpn_keys WHERE expiry_date > datetime('now')")
            return cursor.fetchone()[0] or 0
    except sqlite3.Error as e:
        logging.error(f"Get active keys count error: {e}")
        return 0


def get_expired_keys_count() -> int:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM vpn_keys WHERE expiry_date <= datetime('now')")
            return cursor.fetchone()[0] or 0
    except sqlite3.Error as e:
        logging.error(f"Get expired keys count error: {e}")
        return 0


def get_transactions_stats() -> dict:
    stats = {'total': 0, 'today': 0, 'week': 0, 'month': 0, 'total_amount': 0}
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount_rub), 0) FROM transactions")
            row = cursor.fetchone()
            stats['total'] = row[0] or 0
            stats['total_amount'] = row[1] or 0
            cursor.execute("SELECT COUNT(*) FROM transactions WHERE date(created_date) = date('now')")
            stats['today'] = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM transactions WHERE created_date >= date('now', '-7 days')")
            stats['week'] = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM transactions WHERE created_date >= date('now', '-30 days')")
            stats['month'] = cursor.fetchone()[0] or 0
    except sqlite3.Error as e:
        logging.error(f"Get transactions stats error: {e}")
    return stats

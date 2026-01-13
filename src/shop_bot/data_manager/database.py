import sqlite3
import aiosqlite
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/project/data"))
DB_FILE = DATA_DIR / "data.db"
OLD_DB_FILE = Path("/app/project") / "users.db"
OLD_DATA_DB = Path("/app/project") / "data.db"

_sync_conn: Optional[sqlite3.Connection] = None


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if OLD_DATA_DB.exists() and not DB_FILE.exists():
        import shutil
        shutil.copy(OLD_DATA_DB, DB_FILE)
        logger.info(f"Migrated data.db from {OLD_DATA_DB} to {DB_FILE}")


def get_sync_conn() -> sqlite3.Connection:
    global _sync_conn
    if _sync_conn is None:
        _ensure_data_dir()
        _sync_conn = sqlite3.connect(str(DB_FILE), check_same_thread=False, timeout=30)
        _sync_conn.row_factory = sqlite3.Row
        _sync_conn.execute("PRAGMA journal_mode=WAL")
        _sync_conn.execute("PRAGMA synchronous=FULL")
        _sync_conn.execute("PRAGMA busy_timeout=30000")
    return _sync_conn


def close_connection():
    global _sync_conn
    if _sync_conn:
        _sync_conn.close()
        _sync_conn = None


async def get_async_conn() -> aiosqlite.Connection:
    _ensure_data_dir()
    conn = await aiosqlite.connect(str(DB_FILE), timeout=30)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=FULL")
    return conn


def cleanup_duplicate_settings():
    conn = get_sync_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT key FROM bot_settings")
    keys = [row[0] for row in cursor.fetchall()]
    for key in keys:
        cursor.execute("SELECT value FROM bot_settings WHERE key = ? AND value IS NOT NULL AND value != '' ORDER BY rowid DESC LIMIT 1", (key,))
        row = cursor.fetchone()
        val = row[0] if row else ""
        conn.execute("DELETE FROM bot_settings WHERE key = ?", (key,))
        conn.execute("INSERT INTO bot_settings (key, value) VALUES (?, ?)", (key, val))
    conn.commit()
    logger.info("Duplicate settings cleaned up")


def initialize_db():
    migrate_from_old_db()
    conn = get_sync_conn()
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY, username TEXT, total_spent REAL DEFAULT 0,
        total_months INTEGER DEFAULT 0, trial_used BOOLEAN DEFAULT 0,
        agreed_to_terms BOOLEAN DEFAULT 0, registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_banned BOOLEAN DEFAULT 0, referred_by INTEGER,
        referral_balance REAL DEFAULT 0, referral_balance_all REAL DEFAULT 0)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS vpn_keys (
        key_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        subscription_link TEXT, expiry_date TIMESTAMP, created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        subscription_uuid TEXT)''')
    
    cursor.execute("PRAGMA table_info(vpn_keys)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'subscription_uuid' not in columns:
        cursor.execute("ALTER TABLE vpn_keys ADD COLUMN subscription_uuid TEXT")
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
        transaction_id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT,
        payment_id TEXT UNIQUE, user_id INTEGER NOT NULL, status TEXT NOT NULL,
        amount_rub REAL NOT NULL, amount_currency REAL, currency_name TEXT,
        payment_method TEXT, metadata TEXT, created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS bot_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS support_threads (
        user_id INTEGER PRIMARY KEY, thread_id INTEGER NOT NULL,
        category TEXT, status TEXT DEFAULT 'open', priority TEXT DEFAULT 'normal',
        created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    cursor.execute("PRAGMA table_info(support_threads)")
    st_columns = [col[1] for col in cursor.fetchall()]
    if 'category' not in st_columns:
        cursor.execute("ALTER TABLE support_threads ADD COLUMN category TEXT")
    if 'status' not in st_columns:
        cursor.execute("ALTER TABLE support_threads ADD COLUMN status TEXT DEFAULT 'open'")
    if 'priority' not in st_columns:
        cursor.execute("ALTER TABLE support_threads ADD COLUMN priority TEXT DEFAULT 'normal'")
    if 'created_date' not in st_columns:
        cursor.execute("ALTER TABLE support_threads ADD COLUMN created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS plans (
        plan_id INTEGER PRIMARY KEY AUTOINCREMENT, plan_name TEXT NOT NULL,
        days INTEGER NOT NULL, price REAL NOT NULL)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS platega_pending (
        transaction_id TEXT PRIMARY KEY, metadata TEXT NOT NULL,
        created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS cryptobot_pending (
        invoice_id TEXT PRIMARY KEY, metadata TEXT NOT NULL,
        created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    defaults = {
        "panel_login": "admin", 
        "panel_password": "admin", 
        "about_text": "",
        "terms_url": "", 
        "privacy_url": "", 
        "support_user": "", 
        "support_text": "",
        "channel_url": "", 
        "force_subscription": "true", 
        "receipt_email": "example@example.com",
        "telegram_bot_token": "", 
        "support_bot_token": "", 
        "telegram_bot_username": "",
        "trial_enabled": "true", 
        "trial_duration_days": "3", 
        "enable_referrals": "true",
        "referral_percentage": "10", 
        "referral_discount": "5", 
        "minimum_withdrawal": "100",
        "support_group_id": "", 
        "admin_telegram_id": "", 
        "yookassa_shop_id": "",
        "yookassa_secret_key": "", 
        "sbp_enabled": "false", 
        "cryptobot_token": "",
        "heleket_merchant_id": "", 
        "heleket_api_key": "", 
        "domain": "",
        "ton_wallet_address": "", 
        "tonapi_key": "", 
        "mwshark_api_key": "",
        "platega_merchant_id": "", 
        "platega_secret_key": "", 
        "platega_payment_method": "2",
        "android_url": "https://telegra.ph/Instrukciya-Android-11-09",
        "windows_url": "https://telegra.ph/Instrukciya-Windows-11-09",
        "ios_url": "https://telegra.ph/Instrukcii-ios-11-09",
        "linux_url": "https://telegra.ph/Instrukciya-Linux-11-09",
        "setup_completed": "false"
    }
    
    for key, value in defaults.items():
        cursor.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
    
    conn.commit()
    _hydrate_setup_flag_if_configured()
    cleanup_duplicate_settings()
    logger.info(f"Database initialized at {DB_FILE}")


def _hydrate_setup_flag_if_configured():
    """
    Backfill the setup_completed flag for existing installations that already
    have all critical settings in place to avoid forcing the new wizard.
    """
    try:
        settings = get_all_settings()
        required = ["mwshark_api_key", "telegram_bot_token", "telegram_bot_username", "admin_telegram_id"]
        default_creds = settings.get("panel_login") == "admin" and settings.get("panel_password") == "admin"
        already_configured = all(settings.get(k) for k in required) and not default_creds
        setup_completed = settings.get("setup_completed")
        if already_configured and setup_completed != "true":
            update_setting("setup_completed", "true")
            logger.info("Setup flag auto-enabled for existing configured installation.")
    except Exception as e:
        logger.error(f"Failed to hydrate setup flag: {e}")


def migrate_from_old_db():
    if not OLD_DB_FILE.exists() or DB_FILE.exists():
        return
    logger.info(f"Migrating from {OLD_DB_FILE} to {DB_FILE}")
    try:
        import shutil
        _ensure_data_dir()
        shutil.copy(OLD_DB_FILE, DB_FILE)
        OLD_DB_FILE.rename(OLD_DB_FILE.with_suffix('.db.bak'))
        logger.info("Migration completed")
    except Exception as e:
        logger.error(f"Migration error: {e}")


def get_setting(key: str) -> Optional[str]:
    conn = get_sync_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
    result = cursor.fetchone()
    if result is None:
        return None
    return result[0] or None


def get_all_settings() -> Dict[str, Any]:
    conn = get_sync_conn()
    conn.execute("BEGIN")
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM bot_settings")
    result = {}
    for row in cursor.fetchall():
        result[row['key']] = row['value'] or ''
    conn.execute("COMMIT")
    logger.info(f"get_all_settings returned: {result}")
    return result


def update_setting(key: str, value: str):
    conn = get_sync_conn()
    val = value if value else ""
    conn.execute("DELETE FROM bot_settings WHERE key = ?", (key,))
    conn.execute("INSERT INTO bot_settings (key, value) VALUES (?, ?)", (key, val))
    conn.commit()


def get_user(telegram_id: int) -> Optional[Dict]:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_all_users() -> List[Dict]:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT * FROM users ORDER BY registration_date DESC")
    return [dict(row) for row in cursor.fetchall()]


def register_user_if_not_exists(telegram_id: int, username: str, referrer_id: Optional[int]):
    conn = get_sync_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id FROM users WHERE telegram_id = ?", (telegram_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (telegram_id, username, registration_date, referred_by) VALUES (?, ?, ?, ?)",
                       (telegram_id, username, datetime.now(), referrer_id))
    else:
        cursor.execute("UPDATE users SET username = ? WHERE telegram_id = ?", (username, telegram_id))
    conn.commit()


def ban_user(telegram_id: int):
    conn = get_sync_conn()
    conn.execute("UPDATE users SET is_banned = 1 WHERE telegram_id = ?", (telegram_id,))
    conn.commit()


def unban_user(telegram_id: int):
    conn = get_sync_conn()
    conn.execute("UPDATE users SET is_banned = 0 WHERE telegram_id = ?", (telegram_id,))
    conn.commit()


def set_terms_agreed(telegram_id: int):
    conn = get_sync_conn()
    conn.execute("UPDATE users SET agreed_to_terms = 1 WHERE telegram_id = ?", (telegram_id,))
    conn.commit()


def set_trial_used(telegram_id: int):
    conn = get_sync_conn()
    conn.execute("UPDATE users SET trial_used = 1 WHERE telegram_id = ?", (telegram_id,))
    conn.commit()


def reset_trial(telegram_id: int):
    conn = get_sync_conn()
    conn.execute("UPDATE users SET trial_used = 0 WHERE telegram_id = ?", (telegram_id,))
    conn.commit()


def delete_user(telegram_id: int):
    conn = get_sync_conn()
    conn.execute("DELETE FROM vpn_keys WHERE user_id = ?", (telegram_id,))
    conn.execute("DELETE FROM transactions WHERE user_id = ?", (telegram_id,))
    conn.execute("DELETE FROM support_threads WHERE user_id = ?", (telegram_id,))
    conn.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
    conn.commit()


def update_user_stats(telegram_id: int, amount_spent: float, months_purchased: int):
    conn = get_sync_conn()
    conn.execute("UPDATE users SET total_spent = total_spent + ?, total_months = total_months + ? WHERE telegram_id = ?",
                 (amount_spent, months_purchased, telegram_id))
    conn.commit()


def reset_user_stats(telegram_id: int):
    conn = get_sync_conn()
    conn.execute("UPDATE users SET total_spent = 0, total_months = 0 WHERE telegram_id = ?", (telegram_id,))
    conn.commit()


def add_to_referral_balance(user_id: int, amount: float):
    conn = get_sync_conn()
    conn.execute("UPDATE users SET referral_balance = referral_balance + ? WHERE telegram_id = ?", (amount, user_id))
    conn.commit()


def set_referral_balance(user_id: int, value: float):
    conn = get_sync_conn()
    conn.execute("UPDATE users SET referral_balance = ? WHERE telegram_id = ?", (value, user_id))
    conn.commit()


def set_referral_balance_all(user_id: int, value: float):
    conn = get_sync_conn()
    conn.execute("UPDATE users SET referral_balance_all = ? WHERE telegram_id = ?", (value, user_id))
    conn.commit()


def get_referral_balance(user_id: int) -> float:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT referral_balance FROM users WHERE telegram_id = ?", (user_id,))
    result = cursor.fetchone()
    return float(result[0]) if result else 0.0


def get_referral_count(user_id: int) -> int:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,))
    return cursor.fetchone()[0] or 0


def get_user_keys(user_id: int) -> List[Dict]:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT * FROM vpn_keys WHERE user_id = ? ORDER BY key_id", (user_id,))
    return [dict(row) for row in cursor.fetchall()]


def get_key_by_id(key_id: int) -> Optional[Dict]:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT * FROM vpn_keys WHERE key_id = ?", (key_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_all_keys() -> List[Dict]:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT * FROM vpn_keys")
    return [dict(row) for row in cursor.fetchall()]


def add_new_key(user_id: int, subscription_link: str, expiry_timestamp_ms: int, subscription_uuid: str = None) -> Optional[int]:
    conn = get_sync_conn()
    cursor = conn.cursor()
    expiry_date = datetime.fromtimestamp(expiry_timestamp_ms / 1000)
    cursor.execute("INSERT INTO vpn_keys (user_id, subscription_link, expiry_date, subscription_uuid) VALUES (?, ?, ?, ?)",
                   (user_id, subscription_link, expiry_date, subscription_uuid))
    conn.commit()
    return cursor.lastrowid


def delete_key_by_id(key_id: int):
    conn = get_sync_conn()
    conn.execute("DELETE FROM vpn_keys WHERE key_id = ?", (key_id,))
    conn.commit()


def delete_user_keys(user_id: int):
    conn = get_sync_conn()
    conn.execute("DELETE FROM vpn_keys WHERE user_id = ?", (user_id,))
    conn.commit()


def update_key_info(key_id: int, subscription_link: str, new_expiry_ms: int, subscription_uuid: str = None):
    conn = get_sync_conn()
    expiry_date = datetime.fromtimestamp(new_expiry_ms / 1000)
    if subscription_uuid:
        conn.execute("UPDATE vpn_keys SET subscription_link = ?, expiry_date = ?, subscription_uuid = ? WHERE key_id = ?",
                     (subscription_link, expiry_date, subscription_uuid, key_id))
    else:
        conn.execute("UPDATE vpn_keys SET subscription_link = ?, expiry_date = ? WHERE key_id = ?",
                     (subscription_link, expiry_date, key_id))
    conn.commit()


def update_key_expiry_days(key_id: int, days_delta: int) -> bool:
    conn = get_sync_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT expiry_date FROM vpn_keys WHERE key_id = ?", (key_id,))
    result = cursor.fetchone()
    if result:
        current_expiry = datetime.fromisoformat(str(result[0]))
        new_expiry = current_expiry + timedelta(days=days_delta)
        conn.execute("UPDATE vpn_keys SET expiry_date = ? WHERE key_id = ?", (new_expiry, key_id))
        conn.commit()
        return True
    return False


def set_key_expiry_date(key_id: int, new_expiry: datetime) -> bool:
    conn = get_sync_conn()
    conn.execute("UPDATE vpn_keys SET expiry_date = ? WHERE key_id = ?", (new_expiry, key_id))
    conn.commit()
    return True


def get_next_key_number(user_id: int) -> int:
    return len(get_user_keys(user_id)) + 1


def get_all_plans() -> List[Dict]:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT * FROM plans ORDER BY days")
    return [dict(row) for row in cursor.fetchall()]


def get_plan_by_id(plan_id: int) -> Optional[Dict]:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT * FROM plans WHERE plan_id = ?", (plan_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def create_plan(plan_name: str, days: int, price: float):
    conn = get_sync_conn()
    conn.execute("INSERT INTO plans (plan_name, days, price) VALUES (?, ?, ?)", (plan_name, days, price))
    conn.commit()


def delete_plan(plan_id: int):
    conn = get_sync_conn()
    conn.execute("DELETE FROM plans WHERE plan_id = ?", (plan_id,))
    conn.commit()


def log_transaction(username: str, transaction_id: Optional[str], payment_id: Optional[str], user_id: int,
                    status: str, amount_rub: float, amount_currency: Optional[float], currency_name: Optional[str],
                    payment_method: str, metadata: str):
    conn = get_sync_conn()
    conn.execute("""INSERT INTO transactions (username, payment_id, user_id, status, amount_rub, 
                    amount_currency, currency_name, payment_method, metadata, created_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (username, payment_id, user_id, status, amount_rub, amount_currency, currency_name,
                  payment_method, metadata, datetime.now()))
    conn.commit()


def create_pending_transaction(payment_id: str, user_id: int, amount_rub: float, metadata: dict) -> int:
    conn = get_sync_conn()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO transactions (payment_id, user_id, status, amount_rub, metadata) VALUES (?, ?, ?, ?, ?)",
                   (payment_id, user_id, 'pending', amount_rub, json.dumps(metadata)))
    conn.commit()
    return cursor.lastrowid


def find_and_complete_ton_transaction(payment_id: str, amount_ton: float) -> Optional[Dict]:
    conn = get_sync_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions WHERE payment_id = ? AND status = 'pending'", (payment_id,))
    tx = cursor.fetchone()
    if not tx:
        return None
    conn.execute("UPDATE transactions SET status = 'paid', amount_currency = ?, currency_name = 'TON', payment_method = 'TON' WHERE payment_id = ?",
                 (amount_ton, payment_id))
    conn.commit()
    return json.loads(tx['metadata'])


def create_pending_platega_transaction(transaction_id: str, metadata: str):
    conn = get_sync_conn()
    conn.execute("INSERT OR REPLACE INTO platega_pending (transaction_id, metadata) VALUES (?, ?)", (transaction_id, metadata))
    conn.commit()


def get_pending_platega_transaction(transaction_id: str) -> Optional[Dict]:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT metadata FROM platega_pending WHERE transaction_id = ?", (transaction_id,))
    row = cursor.fetchone()
    if row:
        return json.loads(row['metadata'])
    return None


def delete_pending_platega_transaction(transaction_id: str):
    conn = get_sync_conn()
    conn.execute("DELETE FROM platega_pending WHERE transaction_id = ?", (transaction_id,))
    conn.commit()


def get_all_pending_platega_transactions() -> List[Dict]:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT transaction_id, metadata FROM platega_pending")
    return [{"transaction_id": row['transaction_id'], "metadata": json.loads(row['metadata'])} for row in cursor.fetchall()]


def create_pending_cryptobot_invoice(invoice_id: str, metadata: str):
    conn = get_sync_conn()
    conn.execute("INSERT OR REPLACE INTO cryptobot_pending (invoice_id, metadata) VALUES (?, ?)", (invoice_id, metadata))
    conn.commit()


def get_pending_cryptobot_invoice(invoice_id: str) -> Optional[Dict]:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT metadata FROM cryptobot_pending WHERE invoice_id = ?", (invoice_id,))
    row = cursor.fetchone()
    if row:
        return json.loads(row['metadata'])
    return None


def delete_pending_cryptobot_invoice(invoice_id: str):
    conn = get_sync_conn()
    conn.execute("DELETE FROM cryptobot_pending WHERE invoice_id = ?", (invoice_id,))
    conn.commit()


def get_all_pending_cryptobot_invoices() -> List[Dict]:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT invoice_id, metadata FROM cryptobot_pending")
    return [{"invoice_id": row['invoice_id'], "metadata": json.loads(row['metadata'])} for row in cursor.fetchall()]


def get_paginated_transactions(page: int = 1, per_page: int = 15) -> tuple:
    offset = (page - 1) * per_page
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT COUNT(*) FROM transactions")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT * FROM transactions ORDER BY created_date DESC LIMIT ? OFFSET ?", (per_page, offset))
    transactions = []
    for row in cursor.fetchall():
        tx = dict(row)
        if tx.get('metadata'):
            try:
                meta = json.loads(tx['metadata'])
                tx['host_name'] = meta.get('host_name', 'N/A')
                tx['plan_name'] = meta.get('plan_name', 'N/A')
            except:
                tx['host_name'] = tx['plan_name'] = 'N/A'
        else:
            tx['host_name'] = tx['plan_name'] = 'N/A'
        transactions.append(tx)
    return transactions, total


def get_recent_transactions(limit: int = 15) -> List[Dict]:
    cursor = get_sync_conn().cursor()
    cursor.execute("""SELECT k.key_id, k.created_date, u.telegram_id, u.username
                      FROM vpn_keys k JOIN users u ON k.user_id = u.telegram_id
                      ORDER BY k.created_date DESC LIMIT ?""", (limit,))
    return [dict(row) for row in cursor.fetchall()]


def get_latest_transaction(user_id: int) -> Optional[Dict]:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT * FROM transactions WHERE user_id = ? ORDER BY created_date DESC LIMIT 1", (user_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def add_support_thread(user_id: int, thread_id: int, category: str = None):
    conn = get_sync_conn()
    conn.execute("INSERT OR REPLACE INTO support_threads (user_id, thread_id, category) VALUES (?, ?, ?)", (user_id, thread_id, category))
    conn.commit()


def get_support_thread_id(user_id: int) -> Optional[int]:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT thread_id FROM support_threads WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else None


def get_support_ticket_status(user_id: int) -> Optional[str]:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT status FROM support_threads WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else None


def update_support_ticket_status(user_id: int, status: str):
    conn = get_sync_conn()
    conn.execute("UPDATE support_threads SET status = ? WHERE user_id = ?", (status, user_id))
    conn.commit()


def get_support_ticket_priority(user_id: int) -> Optional[str]:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT priority FROM support_threads WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else None


def update_support_ticket_priority(user_id: int, priority: str):
    conn = get_sync_conn()
    conn.execute("UPDATE support_threads SET priority = ? WHERE user_id = ?", (priority, user_id))
    conn.commit()


def delete_support_thread(user_id: int):
    conn = get_sync_conn()
    conn.execute("DELETE FROM support_threads WHERE user_id = ?", (user_id,))
    conn.commit()


def increment_ticket_messages(user_id: int):
    pass


def add_ticket_note(user_id: int, note: str, author: str):
    pass


def save_support_rating(user_id: int, rating: int):
    pass


def get_user_id_by_thread(thread_id: int) -> Optional[int]:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT user_id FROM support_threads WHERE thread_id = ?", (thread_id,))
    result = cursor.fetchone()
    return result[0] if result else None


def get_user_count() -> int:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    return cursor.fetchone()[0] or 0


def get_total_keys_count() -> int:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT COUNT(*) FROM vpn_keys")
    return cursor.fetchone()[0] or 0


def get_total_spent_sum() -> float:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT SUM(total_spent) FROM users")
    return cursor.fetchone()[0] or 0.0


def get_all_vpn_users() -> List[Dict]:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT DISTINCT user_id FROM vpn_keys")
    return [dict(row) for row in cursor.fetchall()]


def get_daily_stats_for_charts(days: int = 30) -> Dict:
    stats = {'users': {}, 'keys': {}}
    cursor = get_sync_conn().cursor()
    cursor.execute("""SELECT date(registration_date) as day, COUNT(*) FROM users 
                      WHERE registration_date >= date('now', ?) GROUP BY day ORDER BY day""", (f'-{days} days',))
    for row in cursor.fetchall():
        stats['users'][row[0]] = row[1]
    cursor.execute("""SELECT date(created_date) as day, COUNT(*) FROM vpn_keys 
                      WHERE created_date >= date('now', ?) GROUP BY day ORDER BY day""", (f'-{days} days',))
    for row in cursor.fetchall():
        stats['keys'][row[0]] = row[1]
    return stats


def search_users(query: str) -> List[Dict]:
    cursor = get_sync_conn().cursor()
    pattern = f"%{query}%"
    cursor.execute("""SELECT * FROM users WHERE username LIKE ? OR CAST(telegram_id AS TEXT) LIKE ?
                      ORDER BY registration_date DESC""", (pattern, pattern))
    return [dict(row) for row in cursor.fetchall()]


def get_users_with_active_keys() -> List[Dict]:
    cursor = get_sync_conn().cursor()
    cursor.execute("""SELECT DISTINCT u.* FROM users u INNER JOIN vpn_keys k ON u.telegram_id = k.user_id
                      WHERE k.expiry_date > datetime('now') ORDER BY u.registration_date DESC""")
    return [dict(row) for row in cursor.fetchall()]


def get_users_without_keys() -> List[Dict]:
    cursor = get_sync_conn().cursor()
    cursor.execute("""SELECT u.* FROM users u LEFT JOIN vpn_keys k ON u.telegram_id = k.user_id
                      WHERE k.key_id IS NULL ORDER BY u.registration_date DESC""")
    return [dict(row) for row in cursor.fetchall()]


def get_banned_users_count() -> int:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
    return cursor.fetchone()[0] or 0


def get_active_keys_count() -> int:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT COUNT(*) FROM vpn_keys WHERE expiry_date > datetime('now')")
    return cursor.fetchone()[0] or 0


def get_expired_keys_count() -> int:
    cursor = get_sync_conn().cursor()
    cursor.execute("SELECT COUNT(*) FROM vpn_keys WHERE expiry_date <= datetime('now')")
    return cursor.fetchone()[0] or 0


def get_transactions_stats() -> Dict:
    stats = {'total': 0, 'today': 0, 'week': 0, 'month': 0, 'total_amount': 0}
    cursor = get_sync_conn().cursor()
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
    return stats


async def async_get_user(telegram_id: int) -> Optional[Dict]:
    async with await get_async_conn() as conn:
        cursor = await conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def async_get_user_keys(user_id: int) -> List[Dict]:
    async with await get_async_conn() as conn:
        cursor = await conn.execute("SELECT * FROM vpn_keys WHERE user_id = ? ORDER BY key_id", (user_id,))
        return [dict(row) for row in await cursor.fetchall()]


async def async_get_setting(key: str) -> Optional[str]:
    async with await get_async_conn() as conn:
        cursor = await conn.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if row is None:
            return None
        val = row[0]
        return val if val else None


async def async_get_all_plans() -> List[Dict]:
    async with await get_async_conn() as conn:
        cursor = await conn.execute("SELECT * FROM plans ORDER BY days")
        return [dict(row) for row in await cursor.fetchall()]

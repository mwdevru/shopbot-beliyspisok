# VPN Reseller Bot

Telegram-бот для реселлинга VPN подписок через MW API.

**Форк [evansvl/vless-shopbot](https://github.com/evansvl/vless-shopbot)** — переработан для работы через MW API.

## Возможности

| Функция | Статус |
|---------|--------|
| Реселлинг через MW API | ✅ |
| Создание подписок | ✅ |
| Продление подписок | ✅ |
| Отзыв подписок через API | ✅ |
| Веб-панель управления | ✅ |
| Адаптивный дизайн панели | ✅ |
| Гибкие тарифы (1-365 дней) | ✅ |
| YooKassa (карты, СБП) | ✅ |
| CryptoBot | ✅ |
| Heleket | ✅ |
| Реферальная система | ✅ |
| Пробный период | ✅ |
| Принудительная подписка на канал | ✅ |
| Support-бот | ✅ |
| TON оплата | ⚠️ В разработке |

## Требования

- Ubuntu/Debian сервер
- Домен с A-записью на IP сервера
- API ключ от [@mwvpnbot](https://t.me/mwvpnbot)

## Установка

```bash
ssh root@your-server-ip
curl -sSL https://raw.githubusercontent.com/mwdevru/shopbot-beliyspisok/main/install.sh | sudo bash
```

## Настройка

1. Войдите в панель: `https://your-domain.com/login`
2. Логин: `admin` / Пароль: `admin` — **сразу смените!**
3. Укажите:
   - API ключ MW API (из [@mwvpnbot](https://t.me/mwvpnbot))
   - Токен бота (от [@BotFather](https://t.me/BotFather))
   - Username бота (без @)
   - Telegram ID админа (узнать: [@userinfobot](https://t.me/userinfobot))
4. Создайте тарифы
5. Запустите бота

## Платежные системы

### YooKassa
Webhook: `https://your-domain.com/yookassa-webhook`

### CryptoBot
Webhook: `https://your-domain.com/cryptobot-webhook`

### Heleket
Webhook: `https://your-domain.com/heleket-webhook`

## MW API

Документация: [vpn.mwshark.host/api/docs](https://vpn.mwshark.host/api/docs)

| Эндпоинт | Метод | Описание | Используется |
|----------|-------|----------|--------------|
| `/api/v1/balance` | GET | Баланс аккаунта | ✅ Dashboard |
| `/api/v1/tariffs` | GET | Список тарифов | ✅ |
| `/api/v1/calculate` | GET | Расчёт цены | ✅ |
| `/api/v1/subscription/create` | POST | Создание подписки | ✅ Покупка/выдача |
| `/api/v1/subscription/extend` | POST | Продление | ✅ Продление/+дни |
| `/api/v1/subscription/revoke` | POST | Отзыв подписки | ✅ Отзыв ключей |
| `/api/v1/subscription/{user_id}` | GET | Статус подписки | ✅ |
| `/api/v1/grants` | GET | Активные гранты | ✅ |
| `/api/v1/history` | GET | История покупок | ❌ Не используется |

## Управление

```bash
cd shopbot-beliyspisok

docker-compose logs -f      # логи
docker-compose restart      # перезапуск
docker-compose down         # остановка
```

## Структура

```
src/shop_bot/
├── bot/
│   ├── handlers.py      # обработчики команд
│   ├── keyboards.py     # клавиатуры
│   └── support_handlers.py
├── modules/
│   └── mwshark_api.py   # MW API клиент
├── data_manager/
│   └── database.py      # SQLite
└── webhook_server/
    ├── app.py           # Flask + webhooks
    ├── templates/       # HTML шаблоны
    └── static/          # CSS/JS
```

## Лицензия

GPL-3.0 — см. [LICENSE](LICENSE)

---

Оригинал: [evansvl/vless-shopbot](https://github.com/evansvl/vless-shopbot)

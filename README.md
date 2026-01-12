<div align="center">

# VPN Reseller Bot

### Telegram-бот для реселлинга VPN подписок

[![Fork](https://img.shields.io/badge/Fork%20of-vless--shopbot-blue)](https://github.com/evansvl/vless-shopbot)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

**Данный проект является форком [evansvl/vless-shopbot](https://github.com/evansvl/vless-shopbot)**

Переработан для работы через MW API

</div>

---

## О проекте

VPN Reseller Bot — решение для автоматизированной продажи VPN-подписок через Telegram без необходимости иметь собственные VPN-серверы. Бот работает через MW API и предоставляет удобную веб-панель для управления.

## Возможности

- **Реселлинг через MW API** — не нужен свой VPN-сервер
- **Веб-панель** — управление тарифами, пользователями и настройками
- **Гибкие тарифы** — создавайте планы на любое количество дней (1-365)
- **Платежные системы:**
  - YooKassa (карты, СБП)
  - CryptoBot (криптовалюта)
  - Heleket (криптовалюта)
- **Реферальная система** — вознаграждения за приглашенных пользователей
- **Пробный период** — автоматическая выдача тестовых ключей
- **Принудительная подписка** — требование подписки на канал

## Требования

- Сервер Ubuntu/Debian с SSH доступом
- Доменное имя с DNS A-записью на IP сервера
- API ключ от [@mwvpnbot](https://t.me/mwvpnbot)
- Баланс на аккаунте MW VPN

## Установка

### 1. Подключитесь к серверу

```bash
ssh root@your-server-ip
```

### 2. Запустите установщик

```bash
curl -sSL https://raw.githubusercontent.com/mwdevru/shopbot-beliyspisok/main/install.sh | sudo bash
```

### 3. Следуйте инструкциям

Скрипт запросит:
- Доменное имя
- Email для SSL-сертификата

После установки вы получите данные для входа в панель.

## Настройка

### Шаг 1: Получите API ключ

1. Перейдите в бот [@mwvpnbot](https://t.me/mwvpnbot)
2. Получите API ключ в разделе API
3. Пополните баланс

### Шаг 2: Настройте панель

1. Войдите в панель: `https://your-domain.com/login`
2. Логин: `admin`, Пароль: `admin`
3. **Сразу смените пароль!**

### Шаг 3: Заполните настройки

В разделе "Настройки" укажите:

- **API Ключ MW API** — ключ от [@mwvpnbot](https://t.me/mwvpnbot)
- **Токен бота** — получите у [@BotFather](https://t.me/BotFather)
- **Username бота** — без символа @
- **Telegram ID администратора** — узнайте у [@userinfobot](https://t.me/userinfobot)

### Шаг 4: Создайте тарифы

В разделе "Управление Тарифами":
- Название (например: "1 месяц")
- Количество дней (1-365)
- Цена в рублях

### Шаг 5: Запустите бота

Нажмите кнопку "Запустить Бота" в шапке панели.

## Настройка платежей

### YooKassa

1. Получите Shop ID и Secret Key в [личном кабинете YooKassa](https://yookassa.ru)
2. Введите их в настройках панели
3. В YooKassa укажите webhook URL:
   ```
   https://your-domain.com/yookassa-webhook
   ```

### CryptoBot

1. Создайте приложение в [@CryptoBot](https://t.me/CryptoBot) → Crypto Pay
2. Скопируйте токен в настройки панели
3. Включите вебхуки на URL:
   ```
   https://your-domain.com/cryptobot-webhook
   ```

### Heleket

1. Зарегистрируйтесь на [heleket.com](https://heleket.com)
2. Введите Merchant ID и API Key в настройках
3. Webhook настраивается автоматически

## Управление

### Просмотр логов

```bash
cd shopbot-beliyspisok
docker-compose logs -f
```

### Перезапуск

```bash
cd shopbot-beliyspisok
docker-compose restart
```

### Остановка

```bash
cd shopbot-beliyspisok
docker-compose down
```

### Обновление

```bash
curl -sSL https://raw.githubusercontent.com/mwdevru/shopbot-beliyspisok/main/install.sh | sudo bash
```

## Структура проекта

```
shopbot-beliyspisok/
├── src/shop_bot/
│   ├── bot/              # Telegram бот
│   │   ├── handlers.py   # Обработчики команд
│   │   └── keyboards.py  # Клавиатуры
│   ├── modules/
│   │   └── mwshark_api.py # MW API клиент
│   ├── data_manager/
│   │   └── database.py   # Работа с БД
│   └── webhook_server/   # Веб-панель
├── docker-compose.yml
├── Dockerfile
└── install.sh
```

## MW API

Документация API: [vpn.mwshark.host/api/docs](https://vpn.mwshark.host/api/docs)

Основные эндпоинты:
- `GET /api/v1/balance` — баланс аккаунта
- `GET /api/v1/tariffs` — список тарифов
- `POST /api/v1/subscription/create` — создание подписки
- `POST /api/v1/subscription/extend` — продление подписки
- `GET /api/v1/subscription/{user_id}` — статус подписки

## Лицензия

GNU General Public License v3.0 — см. файл [LICENSE](LICENSE)

---

<div align="center">

**Оригинальный проект:** [evansvl/vless-shopbot](https://github.com/evansvl/vless-shopbot)

</div>

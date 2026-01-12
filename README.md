<p align="center">
  <img src="https://img.shields.io/badge/version-1.4.7-blue?style=for-the-badge" alt="Version">
  <img src="https://img.shields.io/badge/python-3.11+-green?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/docker-ready-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/license-GPL--3.0-orange?style=for-the-badge" alt="License">
</p>

<h1 align="center">⚡ MW VPN Reseller Bot</h1>

<p align="center">
  <b>Профессиональный Telegram-бот для реселлинга VPN подписок</b><br>
  <sub>Построен на MW API • Современная веб-панель • Множество платёжных систем</sub>
</p>

<p align="center">
  <a href="#-возможности">Возможности</a> •
  <a href="#-быстрый-старт">Быстрый старт</a> •
  <a href="#-платежи">Платежи</a> •
  <a href="#-api">API</a> •
  <a href="#-документация">Документация</a>
</p>

---

## 🎯 Возможности

<table>
<tr>
<td width="50%">

### 🤖 Telegram Бот
- ✅ Автоматическое создание подписок
- ✅ Продление и отзыв ключей
- ✅ Реферальная система
- ✅ Пробный период
- ✅ Принудительная подписка на канал
- ✅ Support-бот для поддержки

</td>
<td width="50%">

### 🖥 Веб-панель
- ✅ Современный адаптивный дизайн
- ✅ Мониторинг сервера в реальном времени
- ✅ Управление пользователями и ключами
- ✅ Статистика и аналитика
- ✅ Рассылка сообщений
- ✅ Автообновление из панели

</td>
</tr>
<tr>
<td>

### 💳 Платежи
- ✅ YooKassa (карты, СБП)
- ✅ Platega (СБП QR, карты)
- ✅ CryptoBot (криптовалюта)
- ✅ Heleket (криптовалюта)
- ⏳ TON (в разработке)

</td>
<td>

### 📊 Аналитика
- ✅ Dashboard с графиками
- ✅ API статистика (баланс, гранты)
- ✅ История транзакций
- ✅ Экспорт в CSV
- ✅ Поиск и фильтрация

</td>
</tr>
</table>

---

## 🚀 Быстрый старт

### Требования

| Компонент | Минимум |
|-----------|---------|
| ОС | Ubuntu 20.04+ / Debian 11+ |
| RAM | 1 GB |
| Домен | С A-записью на IP сервера |
| API ключ | От [@mwvpnbot](https://t.me/mwvpnbot) |

### Установка

```bash
# Подключитесь к серверу
ssh root@your-server-ip

# Запустите установщик
curl -sSL https://raw.githubusercontent.com/mwdevru/shopbot-beliyspisok/main/install.sh | sudo bash
```

### Первый запуск

1. Откройте панель: `https://your-domain.com/login`
2. Войдите: `admin` / `admin`
3. **Сразу смените пароль!**
4. Настройте:
   - 🔑 API ключ MW API
   - 🤖 Токен бота от [@BotFather](https://t.me/BotFather)
   - 👤 Telegram ID админа
5. Создайте тарифы
6. Запустите бота

---

## 💳 Платежи

### Webhooks

| Система | URL |
|---------|-----|
| YooKassa | `https://your-domain.com/yookassa-webhook` |
| Platega | `https://your-domain.com/platega-webhook` |
| CryptoBot | `https://your-domain.com/cryptobot-webhook` |
| Heleket | `https://your-domain.com/heleket-webhook` |

---

## 🔌 API

Документация MW API: [vpn.mwshark.host/api/docs](https://vpn.mwshark.host/api/docs)

<details>
<summary><b>Используемые эндпоинты</b></summary>

| Эндпоинт | Описание |
|----------|----------|
| `GET /api/v1/balance` | Баланс аккаунта |
| `GET /api/v1/tariffs` | Список тарифов |
| `POST /api/v1/subscription/create` | Создание подписки |
| `POST /api/v1/subscription/extend` | Продление |
| `POST /api/v1/subscription/revoke` | Отзыв подписки |
| `GET /api/v1/subscription/{user_id}` | Статус подписки |
| `GET /api/v1/grants` | Активные гранты |

</details>

---

## 🛠 Управление

```bash
cd shopbot-beliyspisok

# Логи
docker-compose logs -f

# Перезапуск
docker-compose restart

# Остановка
docker-compose down

# Обновление
git pull && docker-compose up -d --build
```

---

## 📁 Структура проекта

```
src/shop_bot/
├── bot/                    # Telegram бот
│   ├── handlers.py         # Обработчики команд
│   ├── keyboards.py        # Клавиатуры
│   └── support_handlers.py # Support-бот
├── modules/
│   └── mwshark_api.py      # MW API клиент
├── data_manager/
│   ├── database.py         # SQLite + миграции
│   └── scheduler.py        # Фоновые задачи
└── webhook_server/
    ├── app.py              # Flask приложение
    ├── templates/          # HTML шаблоны
    └── static/             # CSS/JS ресурсы
```

---

## 📋 Changelog

Полный список изменений: **[CHANGELOG.md](CHANGELOG.md)**

---

## 📄 Лицензия

Распространяется под лицензией **GPL-3.0** — см. [LICENSE](LICENSE)

---

<p align="center">
  <b>© 2026 MW LLC. All rights reserved.</b><br>
  <sub>Форк <a href="https://github.com/evansvl/vless-shopbot">evansvl/vless-shopbot</a></sub>
</p>

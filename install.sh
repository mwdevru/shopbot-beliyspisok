#!/bin/bash

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

set -e

read_input() {
    read -p "$1" "$2" < /dev/tty
}

install_docker_compose() {
    if ! command -v docker-compose &> /dev/null; then
        echo -e "${YELLOW}docker-compose не найден. Устанавливаем...${NC}"
        sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
        sudo chmod +x /usr/local/bin/docker-compose
        echo -e "${GREEN}✔ docker-compose установлен.${NC}"
    fi
}

run_docker() {
    if ! command -v docker-compose &> /dev/null; then
        install_docker_compose
    fi
    
    if [ "$(sudo docker-compose ps -q 2>/dev/null)" ]; then
        sudo docker-compose down --remove-orphans
    fi
    sudo docker-compose up -d --build
}

REPO_URL="https://github.com/mwdevru/shopbot-beliyspisok.git"
PROJECT_DIR="shopbot-beliyspisok"
NGINX_CONF_FILE="/etc/nginx/sites-available/${PROJECT_DIR}.conf"

echo -e "${GREEN}--- Запуск скрипта установки/обновления VPN Reseller Bot ---${NC}"

if [ -f "$NGINX_CONF_FILE" ]; then
    echo -e "\n${CYAN}Обнаружена существующая конфигурация. Скрипт запущен в режиме обновления.${NC}"

    if [ ! -d "$PROJECT_DIR" ]; then
        echo -e "${RED}Ошибка: Конфигурация Nginx существует, но папка проекта '${PROJECT_DIR}' не найдена!${NC}"
        exit 1
    fi

    cd $PROJECT_DIR

    echo -e "\n${CYAN}Шаг 1: Обновление кода из репозитория Git...${NC}"
    git pull
    echo -e "${GREEN}✔ Код успешно обновлен.${NC}"

    echo -e "\n${CYAN}Шаг 2: Пересборка и перезапуск Docker-контейнеров...${NC}"
    run_docker
    
    echo -e "\n\n${GREEN}==============================================${NC}"
    echo -e "${GREEN}      🎉 Обновление успешно завершено! 🎉      ${NC}"
    echo -e "${GREEN}==============================================${NC}"

    exit 0
fi

echo -e "\n${YELLOW}Существующая конфигурация не найдена. Запускается первоначальная установка...${NC}"

echo -e "\n${CYAN}Шаг 1: Установка системных зависимостей...${NC}"
install_package() {
    if ! command -v $1 &> /dev/null; then
        echo -e "${YELLOW}Утилита '$1' не найдена. Устанавливаем...${NC}"
        sudo apt-get update
        sudo apt-get install -y $2
    else
        echo -e "${GREEN}✔ $1 уже установлен.${NC}"
    fi
}

install_package "git" "git"
install_package "docker" "docker.io"
install_package "nginx" "nginx"
install_package "curl" "curl"
install_package "certbot" "certbot python3-certbot-nginx"

install_docker_compose

for service in docker nginx; do
    if ! sudo systemctl is-active --quiet $service; then
        sudo systemctl start $service
        sudo systemctl enable $service
    fi
done
echo -e "${GREEN}✔ Все системные зависимости установлены.${NC}"

echo -e "\n${CYAN}Шаг 2: Клонирование репозитория...${NC}"
if [ ! -d "$PROJECT_DIR" ]; then
    git clone $REPO_URL
fi
cd $PROJECT_DIR
echo -e "${GREEN}✔ Репозиторий готов.${NC}"

echo -e "\n${CYAN}Шаг 3: Настройка домена и получение SSL-сертификатов...${NC}"

read_input "Введите ваш домен (например, my-vpn-shop.com): " USER_INPUT_DOMAIN

if [ -z "$USER_INPUT_DOMAIN" ]; then
    echo -e "${RED}Ошибка: Домен не может быть пустым.${NC}"
    exit 1
fi

DOMAIN=$(echo "$USER_INPUT_DOMAIN" | sed -e 's%^https\?://%%' -e 's%/.*$%%')

read_input "Введите ваш email (для SSL-сертификатов Let's Encrypt): " EMAIL

echo -e "${GREEN}✔ Домен: ${DOMAIN}${NC}"

if command -v ufw &> /dev/null && sudo ufw status | grep -q 'Status: active'; then
    sudo ufw allow 80/tcp
    sudo ufw allow 443/tcp
    sudo ufw allow 1488/tcp
fi

echo -e "\n${CYAN}Шаг 4: Настройка Nginx...${NC}"

NGINX_ENABLED_FILE="/etc/nginx/sites-enabled/${PROJECT_DIR}.conf"

sudo rm -rf /etc/nginx/sites-enabled/default

sudo bash -c "cat > $NGINX_CONF_FILE" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    location / {
        return 200 'OK';
        add_header Content-Type text/plain;
    }
}
EOF

if [ ! -f "$NGINX_ENABLED_FILE" ]; then
    sudo ln -s $NGINX_CONF_FILE $NGINX_ENABLED_FILE
fi

sudo nginx -t && sudo systemctl reload nginx

if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo -e "${GREEN}✔ SSL-сертификаты уже существуют.${NC}"
else
    sudo certbot --nginx -d $DOMAIN --email $EMAIL --agree-tos --non-interactive --redirect
    if [ $? -ne 0 ]; then
        echo -e "${YELLOW}⚠ Автоматическая установка не удалась. Получаем сертификат вручную...${NC}"
        sudo certbot certonly --nginx -d $DOMAIN --email $EMAIL --agree-tos --non-interactive
    fi
    echo -e "${GREEN}✔ SSL-сертификаты получены.${NC}"
fi

if [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
    echo -e "${RED}Ошибка: SSL-сертификаты не найдены!${NC}"
    exit 1
fi

sudo bash -c "cat > $NGINX_CONF_FILE" <<EOF
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    location / {
        proxy_pass http://127.0.0.1:1488;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}

server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    return 301 https://\$server_name\$request_uri;
}
EOF

sudo nginx -t && sudo systemctl reload nginx
echo -e "${GREEN}✔ Nginx настроен с SSL.${NC}"

echo -e "\n${CYAN}Шаг 5: Сборка и запуск Docker-контейнера...${NC}"
run_docker

echo -e "\n\n${GREEN}=====================================================${NC}"
echo -e "${GREEN}      🎉 Установка успешно завершена! 🎉      ${NC}"
echo -e "${GREEN}=====================================================${NC}"
echo -e "\nВеб-панель: ${YELLOW}https://${DOMAIN}/login${NC}"
echo -e "\nЛогин: ${CYAN}admin${NC}"
echo -e "Пароль: ${CYAN}admin${NC}"
echo -e "\n${RED}ВАЖНО:${NC}"
echo -e "1. Смените пароль в настройках панели"
echo -e "2. Получите API ключ в боте https://t.me/mwvpnbot"
echo -e "3. Введите API ключ, токен бота и Telegram ID в настройках"
echo -e "4. Создайте тарифы и запустите бота"
echo -e "\n"

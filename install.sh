#!/bin/bash

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

CHECK="✔"
CROSS="✖"
ARROW="➜"

set -e

LOG_FILE=$(mktemp)
trap "rm -f $LOG_FILE" EXIT

spinner() {
    local pid=$1
    local msg=$2
    local spin='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local i=0
    
    tput civis
    while kill -0 $pid 2>/dev/null; do
        i=$(( (i+1) % 10 ))
        printf "\r  ${CYAN}${spin:$i:1}${NC} %s..." "$msg"
        sleep 0.1
    done
    tput cnorm
}

run_silent() {
    local msg=$1
    shift
    
    "$@" > "$LOG_FILE" 2>&1 &
    local pid=$!
    
    spinner $pid "$msg"
    
    wait $pid
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        printf "\r  ${GREEN}${CHECK}${NC} %s\n" "$msg"
    else
        printf "\r  ${RED}${CROSS}${NC} %s\n" "$msg"
        echo -e "\n${RED}Ошибка:${NC}"
        cat "$LOG_FILE"
        return $exit_code
    fi
}

step_header() {
    echo -e "\n${BOLD}${CYAN}${ARROW} $1${NC}"
}

read_input() {
    read -p "$1" "$2" < /dev/tty
}

install_docker_compose() {
    if ! command -v docker-compose &> /dev/null; then
        run_silent "Установка docker-compose" bash -c 'sudo curl -sL "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose && sudo chmod +x /usr/local/bin/docker-compose'
    fi
}

run_docker() {
    if ! command -v docker-compose &> /dev/null; then
        install_docker_compose
    fi
    
    if [ "$(sudo docker-compose ps -q 2>/dev/null)" ]; then
        run_silent "Остановка старых контейнеров" sudo docker-compose down --remove-orphans
    fi
    run_silent "Сборка и запуск контейнеров" sudo docker-compose up -d --build
}

REPO_URL="https://github.com/mwdevru/shopbot-beliyspisok.git"
PROJECT_DIR="shopbot-beliyspisok"
NGINX_CONF_FILE="/etc/nginx/sites-available/${PROJECT_DIR}.conf"

clear
echo ""
echo -e "${BOLD}${GREEN}╔════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║       🤖 VPN Reseller Bot - Установщик             ║${NC}"
echo -e "${BOLD}${GREEN}╚════════════════════════════════════════════════════╝${NC}"
echo ""

update_nginx_config() {
    local domain=$(grep -oP 'server_name \K[^;]+' "$NGINX_CONF_FILE" | head -1)
    local need_update=0
    
    sudo cp -f src/shop_bot/webhook_server/static/502.html /var/www/html/502.html 2>/dev/null
    
    grep -q "error_page 502" "$NGINX_CONF_FILE" || need_update=1
    grep -q "root /var/www/html" "$NGINX_CONF_FILE" || need_update=1
    
    if [ $need_update -eq 1 ]; then
        sudo bash -c "cat > $NGINX_CONF_FILE" <<NGINXEOF
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${domain};

    ssl_certificate /etc/letsencrypt/live/${domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${domain}/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    error_page 502 503 504 /502.html;
    location = /502.html {
        root /var/www/html;
        internal;
    }

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
    server_name ${domain};
    return 301 https://\$server_name\$request_uri;
}
NGINXEOF
        sudo nginx -t && sudo systemctl reload nginx
        return 0
    fi
    return 1
}

if [ -f "$NGINX_CONF_FILE" ]; then
    echo -e "${YELLOW}Обнаружена существующая установка. Режим: ${BOLD}ОБНОВЛЕНИЕ${NC}"
    
    if [ ! -d "$PROJECT_DIR" ]; then
        echo -e "${RED}${CROSS} Папка проекта '${PROJECT_DIR}' не найдена!${NC}"
        exit 1
    fi

    cd $PROJECT_DIR

    step_header "Обновление кода"
    run_silent "Получение обновлений из Git" git pull

    step_header "Проверка конфигурации"
    if update_nginx_config 2>/dev/null; then
        echo -e "  ${GREEN}${CHECK}${NC} Nginx конфиг обновлён"
    else
        echo -e "  ${GREEN}${CHECK}${NC} Nginx конфиг актуален"
    fi
    sudo cp -f src/shop_bot/webhook_server/static/502.html /var/www/html/502.html 2>/dev/null
    echo -e "  ${GREEN}${CHECK}${NC} Страница 502 обновлена"

    step_header "Перезапуск сервисов"
    run_docker
    
    echo ""
    echo -e "${BOLD}${GREEN}╔════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${GREEN}║         🎉 Обновление завершено!                   ║${NC}"
    echo -e "${BOLD}${GREEN}╚════════════════════════════════════════════════════╝${NC}"
    echo ""
    exit 0
fi

echo -e "${YELLOW}Режим: ${BOLD}ПЕРВОНАЧАЛЬНАЯ УСТАНОВКА${NC}"

step_header "Установка системных зависимостей"

install_package() {
    local cmd=$1
    local pkg=$2
    if ! command -v $cmd &> /dev/null; then
        run_silent "Установка $pkg" bash -c "sudo apt-get update -qq && sudo apt-get install -y -qq $pkg"
    else
        echo -e "  ${GREEN}${CHECK}${NC} $cmd уже установлен"
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
        run_silent "Запуск $service" bash -c "sudo systemctl start $service && sudo systemctl enable $service"
    fi
done

step_header "Подготовка проекта"
if [ ! -d "$PROJECT_DIR" ]; then
    run_silent "Клонирование репозитория" git clone --quiet $REPO_URL
else
    echo -e "  ${GREEN}${CHECK}${NC} Репозиторий уже существует"
fi
cd $PROJECT_DIR

step_header "Настройка домена"
echo ""
read_input "  Введите домен (например: my-vpn-shop.com): " USER_INPUT_DOMAIN

if [ -z "$USER_INPUT_DOMAIN" ]; then
    echo -e "  ${RED}${CROSS} Домен не может быть пустым${NC}"
    exit 1
fi

DOMAIN=$(echo "$USER_INPUT_DOMAIN" | sed -e 's%^https\?://%%' -e 's%/.*$%%')
read_input "  Введите email (для SSL): " EMAIL
echo -e "  ${GREEN}${CHECK}${NC} Домен: ${BOLD}${DOMAIN}${NC}"

if command -v ufw &> /dev/null && sudo ufw status | grep -q 'Status: active'; then
    run_silent "Настройка firewall" bash -c "sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw allow 1488/tcp"
fi

step_header "Настройка Nginx"

NGINX_ENABLED_FILE="/etc/nginx/sites-enabled/${PROJECT_DIR}.conf"
sudo rm -rf /etc/nginx/sites-enabled/default 2>/dev/null || true

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
    sudo ln -s $NGINX_CONF_FILE $NGINX_ENABLED_FILE 2>/dev/null || true
fi

run_silent "Проверка конфигурации Nginx" bash -c "sudo nginx -t && sudo systemctl reload nginx"

step_header "Получение SSL-сертификата"
if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo -e "  ${GREEN}${CHECK}${NC} SSL-сертификат уже существует"
else
    run_silent "Получение сертификата Let's Encrypt" sudo certbot --nginx -d $DOMAIN --email $EMAIL --agree-tos --non-interactive --redirect
fi

if [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
    echo -e "  ${RED}${CROSS} SSL-сертификат не найден!${NC}"
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

    error_page 502 503 504 /502.html;
    location = /502.html {
        root /var/www/html;
        internal;
    }

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

sudo cp -f src/shop_bot/webhook_server/static/502.html /var/www/html/502.html
echo -e "  ${GREEN}${CHECK}${NC} Страница 502 установлена"

run_silent "Применение SSL-конфигурации" bash -c "sudo nginx -t && sudo systemctl reload nginx"

step_header "Запуск приложения"
run_docker

echo ""
echo -e "${BOLD}${GREEN}╔════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║         🎉 Установка завершена!                    ║${NC}"
echo -e "${BOLD}${GREEN}╚════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}Веб-панель:${NC}  https://${DOMAIN}/login"
echo -e "  ${CYAN}Логин:${NC}       admin"
echo -e "  ${CYAN}Пароль:${NC}      admin"
echo ""
echo -e "${YELLOW}Следующие шаги:${NC}"
echo -e "  1. Смените пароль в настройках панели"
echo -e "  2. Получите API ключ: ${CYAN}https://t.me/mwvpnbot${NC}"
echo -e "  3. Введите API ключ, токен бота и Telegram ID"
echo -e "  4. Создайте тарифы и запустите бота"
echo ""

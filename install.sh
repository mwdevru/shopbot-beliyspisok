#!/bin/bash

rm -f /tmp/shopbot_install_state.json 2>/dev/null || true
sudo killall apt apt-get 2>/dev/null || true
sudo rm -f /var/lib/apt/lists/lock /var/cache/apt/archives/lock /var/lib/dpkg/lock* 2>/dev/null || true
sudo dpkg --configure -a 2>/dev/null || true

set -uo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

CHECK="✔"
CROSS="✖"
ARROW="➜"

LOG_FILE=$(mktemp)
STATE_FILE="/tmp/shopbot_install_state.json"
LOCK_FILE="/tmp/shopbot_install.lock"

trap cleanup EXIT INT TERM

cleanup() {
    local exit_code=$?
    rm -f "$LOG_FILE" "$LOCK_FILE" 2>/dev/null || true
    tput cnorm 2>/dev/null || true
    if [ $exit_code -ne 0 ] && [ $exit_code -ne 130 ]; then
        echo -e "\n${RED}${CROSS} Установка прервана.${NC}"
        if [ -f "$LOG_FILE" ]; then
            echo -e "${RED}Логи ошибки:${NC}"
            tail -n 10 "$LOG_FILE"
        fi
    elif [ $exit_code -eq 130 ]; then
        echo -e "\n${RED}${CROSS} Отменено пользователем.${NC}"
    fi
    exit $exit_code
}

acquire_lock() {
    if [ -f "$LOCK_FILE" ]; then
        local pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo -e "${RED}${CROSS} Установка уже запущена (PID: $pid)${NC}"
            exit 1
        fi
    fi
    echo $$ > "$LOCK_FILE"
}

save_state() {
    local step=$1
    local data=${2:-"{}"}
    cat > "$STATE_FILE" <<EOF
{
    "step": "$step",
    "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "data": $data
}
EOF
}

load_state() {
    if [ -f "$STATE_FILE" ]; then
        cat "$STATE_FILE"
    else
        echo '{"step":"start","data":{}}'
    fi
}

get_state_step() {
    load_state | grep -oP '"step":\s*"\K[^"]+' || echo "start"
}

get_state_data() {
    local key=$1
    load_state | grep -oP "\"$key\":\s*\"\K[^\"]+\"" || echo ""
}

clear_state() {
    rm -f "$STATE_FILE"
}

spinner() {
    local pid=$1
    local msg=$2
    local spin='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local i=0
    
    tput civis 2>/dev/null || true
    while kill -0 $pid 2>/dev/null; do
        i=$(( (i+1) % 10 ))
        printf "\r  ${CYAN}${spin:$i:1}${NC} %s..." "$msg"
        sleep 0.1
    done
    tput cnorm 2>/dev/null || true
}

run_silent() {
    local msg=$1
    local max_retries=${2:-3}
    shift 2
    
    local attempt=1
    while [ $attempt -le $max_retries ]; do
        "$@" >> "$LOG_FILE" 2>&1 &
        local pid=$!
        
        spinner $pid "$msg"
        
        wait $pid
        local exit_code=$?
        
        if [ $exit_code -eq 0 ]; then
            printf "\r  ${GREEN}${CHECK}${NC} %s\n" "$msg"
            return 0
        else
            if [ $attempt -lt $max_retries ]; then
                printf "\r  ${YELLOW}⚠${NC} %s (попытка %d/%d)\n" "$msg" "$attempt" "$max_retries"
                if auto_fix_error; then
                    printf "  ${GREEN}${CHECK}${NC} Исправлено\n"
                else
                    sleep 2
                fi
                attempt=$((attempt + 1))
            else
                printf "\r  ${RED}${CROSS}${NC} %s\n" "$msg"
                return $exit_code
            fi
        fi
    done
    return 1
}

auto_fix_error() {
    local error=$(tail -n 20 "$LOG_FILE")
    
    if echo "$error" | grep -qi "dpkg.*lock"; then
        sudo rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock 2>/dev/null || true
        sudo dpkg --configure -a 2>/dev/null || true
        return 0
    fi
    
    if echo "$error" | grep -qi "Could not get lock"; then
        sudo killall apt apt-get 2>/dev/null || true
        sleep 5
        return 0
    fi
    
    if echo "$error" | grep -qi "docker.*not running\|Cannot connect to the Docker daemon"; then
        sudo systemctl restart docker
        sleep 5
        return 0
    fi
    
    if echo "$error" | grep -qi "port.*already in use\|address already in use"; then
        local port=$(echo "$error" | grep -oP '\d+' | head -1)
        if [ -n "$port" ]; then
            sudo fuser -k ${port}/tcp 2>/dev/null || true
            sleep 2
            return 0
        fi
    fi
    
    return 1
}

step_header() {
    echo -e "\n${BOLD}${CYAN}${ARROW} $1${NC}"
}

read_input() {
    local prompt=$1
    local var_name=$2
    local saved_value=$(get_state_data "$var_name")
    
    if [ -n "$saved_value" ]; then
        eval "$var_name='$saved_value'"
        return 0
    fi
    
    if [ ! -t 0 ]; then
        return 1
    fi
    
    local value=""
    while [ -z "$value" ]; do
        echo -e -n "  $prompt"
        read -r value
    done
    
    eval "$var_name='$value'"
    save_state "input_$var_name" "{\"$var_name\":\"$value\"}"
    return 0
}

install_docker_compose() {
    if ! command -v docker-compose &> /dev/null; then
        run_silent "Установка docker-compose" 3 bash -c "
            sudo curl -sL \"https://github.com/docker/compose/releases/latest/download/docker-compose-\$(uname -s)-\$(uname -m)\" -o /usr/local/bin/docker-compose && 
            sudo chmod +x /usr/local/bin/docker-compose &&
            docker-compose --version
        "
    fi
}

run_docker() {
    if ! command -v docker-compose &> /dev/null; then
        install_docker_compose
    fi
    
    if ! sudo systemctl is-active --quiet docker; then
        run_silent "Запуск Docker" 2 sudo systemctl start docker
        sleep 3
    fi
    
    if [ ! -f "docker-compose.yml" ]; then
        return 1
    fi

    if [ "$(sudo docker-compose ps -q 2>/dev/null)" ]; then
        run_silent "Остановка старых контейнеров" 2 sudo docker-compose down --remove-orphans || true
    fi
    
    run_silent "Сборка и запуск" 3 bash -c "
        sudo docker-compose build --no-cache --quiet &&
        sudo docker-compose up -d &&
        sleep 5 &&
        sudo docker-compose ps | grep -q \"Up\"
    " || return 1
}

REPO_URL="https://github.com/mwdevru/shopbot-beliyspisok.git"
PROJECT_DIR="shopbot-beliyspisok"
NGINX_CONF_FILE="/etc/nginx/sites-available/${PROJECT_DIR}.conf"

check_system() {
    if ! command -v sudo &> /dev/null; then
        echo -e "${RED}${CROSS} sudo не установлен${NC}"
        exit 1
    fi
    
    local free_space=$(df / | awk 'NR==2 {print $4}')
    if [ "$free_space" -lt 2097152 ]; then
        echo -e "${YELLOW}⚠ Мало места на диске (< 2GB)${NC}"
        sudo apt-get autoremove -y -qq 2>/dev/null || true
        sudo apt-get clean 2>/dev/null || true
        sudo docker system prune -af 2>/dev/null || true
    fi
    
    if ! ping -c 1 8.8.8.8 &>/dev/null; then
        if ! ping -c 1 1.1.1.1 &>/dev/null; then
            echo -e "${RED}${CROSS} Нет интернета${NC}"
            exit 1
        fi
    fi
}

acquire_lock

clear
echo ""
echo -e "${BOLD}${GREEN}╔════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║       🤖 VPN Reseller Bot - Установщик             ║${NC}"
echo -e "${BOLD}${GREEN}╚════════════════════════════════════════════════════╝${NC}"
echo ""

check_system

CURRENT_STEP=$(get_state_step)
if [ "$CURRENT_STEP" != "start" ] && [ "$CURRENT_STEP" != "completed" ]; then
    echo -e "${YELLOW}Продолжаем установку с этапа: ${BOLD}${CURRENT_STEP}${NC}\n"
    sleep 2
fi

update_nginx_config() {
    local domain=$(grep -oP 'server_name \K[^;]+' "$NGINX_CONF_FILE" | head -1 | tr -d ' ')
    
    if [ -z "$domain" ]; then 
        return 1
    fi

    if ! grep -q "error_page 502" "$NGINX_CONF_FILE" || ! grep -q "root /var/www/html" "$NGINX_CONF_FILE"; then
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

if [ -f "$NGINX_CONF_FILE" ] && [ "$CURRENT_STEP" == "start" ]; then
    echo -e "${YELLOW}Режим: ${BOLD}ОБНОВЛЕНИЕ${NC}"
    
    if [ ! -d "$PROJECT_DIR" ]; then
        step_header "Восстановление"
        run_silent "Клонирование" 3 git clone --depth 1 $REPO_URL
        if [ ! -d "$PROJECT_DIR" ]; then
            echo -e "${RED}${CROSS} Ошибка восстановления${NC}"
            exit 1
        fi
    fi

    cd "$PROJECT_DIR" || exit 1
    save_state "update_started"

    step_header "Обновление"
    if [ -d ".git" ]; then
        run_silent "git pull" 3 bash -c 'git fetch --all && git reset --hard origin/main && git pull'
    else
        cd ..
        sudo rm -rf "$PROJECT_DIR"
        run_silent "Переклонирование" 3 git clone --depth 1 $REPO_URL
        cd "$PROJECT_DIR" || exit 1
    fi
    save_state "code_updated"

    step_header "Конфигурация"
    if update_nginx_config 2>/dev/null; then
        echo -e "  ${GREEN}${CHECK}${NC} Nginx обновлён"
    else
        echo -e "  ${GREEN}${CHECK}${NC} Nginx актуален"
    fi
    
    sudo mkdir -p /var/www/html 2>/dev/null || true
    if [ -f "src/shop_bot/webhook_server/static/502.html" ]; then
        sudo cp -f src/shop_bot/webhook_server/static/502.html /var/www/html/502.html
        echo -e "  ${GREEN}${CHECK}${NC} Страница 502 обновлена"
    fi
    save_state "config_updated"

    step_header "Перезапуск"
    run_docker
    save_state "completed"
    clear_state
    
    echo ""
    echo -e "${BOLD}${GREEN}🎉 Обновление завершено!${NC}"
    exit 0
fi

echo -e "${YELLOW}Режим: ${BOLD}УСТАНОВКА${NC}"

if [ "$CURRENT_STEP" == "start" ] || [ "$CURRENT_STEP" == "dependencies" ]; then
    step_header "Зависимости"
    save_state "dependencies"
    
    sudo killall apt apt-get 2>/dev/null || true
    sudo dpkg --configure -a 2>/dev/null || true

    install_package() {
        local cmd=$1
        local pkg=$2
        
        if ! command -v $cmd &> /dev/null; then
            printf "  ⠋ $pkg..."
            if sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1; then
                if sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$pkg" >/dev/null 2>&1; then
                    printf "\r  ${GREEN}${CHECK}${NC} $pkg установлен          \n"
                    return 0
                else
                    printf "\r  ${YELLOW}⚠${NC} $pkg ошибка установки     \n"
                    return 1
                fi
            else
                printf "\r  ${YELLOW}⚠${NC} apt ошибка              \n"
                return 1
            fi
        else
            echo -e "  ${GREEN}${CHECK}${NC} $cmd ok"
            return 0
        fi
    }

    install_package "git" "git"
    install_package "docker" "docker.io"
    install_package "nginx" "nginx"
    install_package "curl" "curl"
    install_package "certbot" "certbot"
    
    if ! dpkg -l | grep -q "python3-certbot-nginx"; then
        printf "  ⠋ python3-certbot-nginx..."
        if sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "python3-certbot-nginx" >/dev/null 2>&1; then
            printf "\r  ${GREEN}${CHECK}${NC} python3-certbot-nginx установлен\n"
        else
            printf "\r  ${YELLOW}⚠${NC} ошибка python3-certbot-nginx \n"
        fi
    else
        echo -e "  ${GREEN}${CHECK}${NC} python3-certbot-nginx ok"
    fi
    
    install_docker_compose

    for service in docker nginx; do
        sudo systemctl enable $service --now 2>/dev/null || true
    done
    save_state "dependencies_done"
fi

if [ "$CURRENT_STEP" == "start" ] || [ "$CURRENT_STEP" == "dependencies_done" ] || [ "$CURRENT_STEP" == "clone" ]; then
    step_header "Проект"
    save_state "clone"
    
    if [ ! -d "$PROJECT_DIR" ]; then
        run_silent "Клонирование" 3 git clone --depth 1 $REPO_URL
    else
        echo -e "  ${GREEN}${CHECK}${NC} Уже существует"
    fi
    cd "$PROJECT_DIR" || exit 1
    save_state "clone_done"
else
    cd "$PROJECT_DIR" 2>/dev/null || {
        echo -e "${RED}${CROSS} Директория не найдена${NC}"
        clear_state
        exit 1
    }
fi

if [ "$CURRENT_STEP" == "start" ] || [ "$CURRENT_STEP" == "clone_done" ] || [ "$CURRENT_STEP" == "domain" ]; then
    step_header "Домен"
    save_state "domain"
    echo ""
    
    USER_INPUT_DOMAIN=""
    EMAIL=""
    
    read_input "Введите домен: " USER_INPUT_DOMAIN
    DOMAIN=$(echo "$USER_INPUT_DOMAIN" | sed -e 's%^https\?://%%' -e 's%/.*$%%' -e 's/[^a-zA-Z0-9.-]//g')
    
    read_input "Введите email: " EMAIL
    if ! echo "$EMAIL" | grep -qE '^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'; then
        EMAIL="admin@example.com"
    fi
    
    echo -e "  ${GREEN}${CHECK}${NC} Домен: ${BOLD}${DOMAIN}${NC}"
    echo -e "  ${GREEN}${CHECK}${NC} Email: ${BOLD}${EMAIL}${NC}"
    save_state "domain_done" "{\"DOMAIN\":\"$DOMAIN\",\"EMAIL\":\"$EMAIL\"}"
else
    DOMAIN=$(get_state_data "DOMAIN")
    EMAIL=$(get_state_data "EMAIL")
    [ -z "$DOMAIN" ] && DOMAIN="vpn.example.com"
    [ -z "$EMAIL" ] && EMAIL="admin@example.com"
    echo -e "  ${GREEN}Используется: ${BOLD}${DOMAIN}${NC}"
fi

if [ "$CURRENT_STEP" == "start" ] || [ "$CURRENT_STEP" == "domain_done" ] || [ "$CURRENT_STEP" == "firewall" ]; then
    save_state "firewall"
    if command -v ufw &> /dev/null && sudo ufw status | grep -q 'Status: active'; then
        run_silent "Firewall" 2 bash -c "
            sudo ufw allow 80/tcp 2>/dev/null || true &&
            sudo ufw allow 443/tcp 2>/dev/null || true &&
            sudo ufw allow 1488/tcp 2>/dev/null || true
        "
    fi
    save_state "firewall_done"
fi

if [ "$CURRENT_STEP" == "start" ] || [ "$CURRENT_STEP" == "firewall_done" ] || [ "$CURRENT_STEP" == "nginx" ]; then
    step_header "Nginx"
    save_state "nginx"

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

    run_silent "Проверка Nginx" 2 bash -c "sudo nginx -t && sudo systemctl reload nginx"
    save_state "nginx_done"
fi

if [ "$CURRENT_STEP" == "start" ] || [ "$CURRENT_STEP" == "nginx_done" ] || [ "$CURRENT_STEP" == "ssl" ]; then
    step_header "SSL"
    save_state "ssl"
    
    if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
        echo -e "  ${GREEN}${CHECK}${NC} SSL уже есть"
    else
        run_silent "Certbot" 3 bash -c "
            sudo certbot --nginx -d $DOMAIN --email $EMAIL --agree-tos --non-interactive --redirect --quiet
        " || true
    fi

    if [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
        echo -e "  ${RED}${CROSS} SSL не получен. Проверьте DNS.${NC}"
    else
        save_state "ssl_done"
    fi
fi

if [ "$CURRENT_STEP" == "start" ] || [ "$CURRENT_STEP" == "ssl_done" ] || [ "$CURRENT_STEP" == "final_config" ]; then
    save_state "final_config"
    
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

    sudo mkdir -p /var/www/html 2>/dev/null || true
    sudo cp -f src/shop_bot/webhook_server/static/502.html /var/www/html/502.html 2>/dev/null || true
    
    run_silent "Применение SSL" 2 bash -c "sudo nginx -t && sudo systemctl reload nginx"
    save_state "final_config_done"
fi

if [ "$CURRENT_STEP" == "start" ] || [ "$CURRENT_STEP" == "final_config_done" ] || [ "$CURRENT_STEP" == "docker" ]; then
    step_header "Запуск"
    save_state "docker"
    
    if [ ! -f ".env" ]; then
        touch .env
    fi
    
    run_docker
    save_state "completed"
    clear_state
fi

echo ""
echo -e "${BOLD}${GREEN}🎉 Установка завершена!${NC}"
echo ""
echo -e "  ${CYAN}Панель:${NC}  https://${DOMAIN}/login"
echo -e "  ${CYAN}Логин:${NC}   admin"
echo -e "  ${CYAN}Пароль:${NC}  admin"
echo ""

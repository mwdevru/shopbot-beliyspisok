#!/bin/bash

rm -f /tmp/shopbot_install_state.json 2>/dev/null || true
sudo pkill -9 apt-get 2>/dev/null || true
sudo pkill -9 apt 2>/dev/null || true
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
    rm -f "$LOG_FILE" "$LOCK_FILE" "$STATE_FILE" 2>/dev/null || true
    tput cnorm 2>/dev/null || true
    [ $exit_code -ne 0 ] && [ $exit_code -ne 130 ] && echo -e "\n${RED}${CROSS} Установка прервана.${NC}"
    [ $exit_code -eq 130 ] && echo -e "\n${RED}${CROSS} Отменено пользователем.${NC}"
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
        "$@" > "$LOG_FILE" 2>&1 &
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
                sleep 2
                attempt=$((attempt + 1))
            else
                printf "\r  ${RED}${CROSS}${NC} %s\n" "$msg"
                echo -e "\n${RED}Ошибка после $max_retries попыток:${NC}"
                cat "$LOG_FILE"
                
                echo -e "\n${YELLOW}Попытка автоматического исправления...${NC}"
                if auto_fix_error "$@"; then
                    printf "  ${GREEN}${CHECK}${NC} Проблема исправлена\n"
                    return 0
                fi
                return $exit_code
            fi
        fi
    done
}

auto_fix_error() {
    local cmd="$*"
    local error=$(cat "$LOG_FILE")
    
    if echo "$error" | grep -qi "dpkg.*lock"; then
        echo "  Обнаружена блокировка dpkg, ожидание..."
        sudo rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock 2>/dev/null || true
        sudo dpkg --configure -a 2>/dev/null || true
        sleep 3
        return 0
    fi
    
    if echo "$error" | grep -qi "Could not get lock"; then
        echo "  Ожидание освобождения apt..."
        sudo killall apt apt-get 2>/dev/null || true
        sleep 5
        return 0
    fi
    
    if echo "$error" | grep -qi "Failed to fetch\|Unable to connect\|Could not resolve\|Temporary failure"; then
        echo "  Проблема с сетью, смена зеркала..."
        sudo sed -i.bak 's/archive.ubuntu.com/mirror.yandex.ru\/ubuntu/g' /etc/apt/sources.list 2>/dev/null || true
        sudo apt-get update -qq 2>/dev/null || true
        return 0
    fi
    
    if echo "$error" | grep -qi "docker.*not running\|Cannot connect to the Docker daemon"; then
        echo "  Перезапуск Docker..."
        sudo systemctl restart docker
        sleep 5
        return 0
    fi
    
    if echo "$error" | grep -qi "nginx.*failed\|nginx.*error"; then
        echo "  Проверка конфигурации Nginx..."
        sudo nginx -t 2>&1 | tail -5
        sudo systemctl restart nginx 2>/dev/null || true
        return 0
    fi
    
    if echo "$error" | grep -qi "port.*already in use\|address already in use"; then
        echo "  Освобождение занятого порта..."
        local port=$(echo "$error" | grep -oP '\d+' | head -1)
        if [ -n "$port" ]; then
            sudo fuser -k ${port}/tcp 2>/dev/null || true
            sleep 2
            return 0
        fi
    fi
    
    if echo "$error" | grep -qi "disk.*full\|No space left"; then
        echo "  Очистка диска..."
        sudo docker system prune -af --volumes 2>/dev/null || true
        sudo apt-get clean 2>/dev/null || true
        sudo journalctl --vacuum-time=3d 2>/dev/null || true
        return 0
    fi
    
    if echo "$error" | grep -qi "fatal: not a git repository\|fatal: destination path.*already exists"; then
        echo "  Исправление Git репозитория..."
        if [ -d "$PROJECT_DIR" ]; then
            cd ..
            sudo rm -rf "$PROJECT_DIR"
        fi
        return 0
    fi
    
    if echo "$error" | grep -qi "Permission denied\|Operation not permitted"; then
        echo "  Исправление прав доступа..."
        if [ -d "$PROJECT_DIR" ]; then
            sudo chown -R $USER:$USER "$PROJECT_DIR" 2>/dev/null || true
        fi
        return 0
    fi
    
    if echo "$error" | grep -qi "certbot.*failed\|Challenge failed\|Timeout during connect"; then
        echo "  Проблема с получением SSL..."
        echo "  Проверьте DNS записи для домена"
        sudo systemctl restart nginx 2>/dev/null || true
        sleep 3
        return 0
    fi
    
    if echo "$error" | grep -qi "docker-compose.*not found\|docker-compose: command not found"; then
        echo "  Переустановка docker-compose..."
        sudo rm -f /usr/local/bin/docker-compose 2>/dev/null || true
        sudo curl -sL "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
        sudo chmod +x /usr/local/bin/docker-compose
        return 0
    fi
    
    if echo "$error" | grep -qi "No such file or directory"; then
        echo "  Восстановление отсутствующих файлов..."
        if [ ! -d "$PROJECT_DIR" ]; then
            git clone --depth 1 $REPO_URL 2>/dev/null || true
        fi
        return 0
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
    
    if [ ! -t 0 ] 2>/dev/null; then
        return 1
    fi
    
    local value=""
    echo -e -n "  $prompt"
    if IFS= read -r -t 30 value 2>/dev/null; then
        if [ -n "$value" ]; then
            eval "$var_name='$value'"
            save_state "input_$var_name" "{\"$var_name\":\"$value\"}"
            return 0
        fi
    fi
    
    return 1
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
    
    if [ "$(sudo docker-compose ps -q 2>/dev/null)" ]; then
        run_silent "Остановка старых контейнеров" 2 sudo docker-compose down --remove-orphans || true
    fi
    
    run_silent "Сборка и запуск контейнеров" 3 bash -c "
        sudo docker-compose build --no-cache --quiet &&
        sudo docker-compose up -d &&
        sleep 5 &&
        sudo docker-compose ps | grep -q \"Up\"
    " || true
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
        echo -e "${YELLOW}⚠ Предупреждение: Мало места на диске (< 2GB)${NC}"
        echo -e "${YELLOW}Попытка очистки...${NC}"
        sudo apt-get autoremove -y -qq 2>/dev/null || true
        sudo apt-get clean 2>/dev/null || true
        sudo docker system prune -af 2>/dev/null || true
    fi
    
    if ! ping -c 1 8.8.8.8 &>/dev/null; then
        echo -e "${YELLOW}⚠ Проблема с подключением к интернету${NC}"
        echo -e "${YELLOW}Проверяем альтернативные DNS...${NC}"
        if ! ping -c 1 1.1.1.1 &>/dev/null; then
            echo -e "${RED}${CROSS} Нет подключения к интернету${NC}"
            exit 1
        fi
    fi
    
    if [ -f "$NGINX_CONF_FILE" ] && [ ! -d "$PROJECT_DIR" ]; then
        echo -e "${YELLOW}⚠ Обнаружена сломанная установка${NC}"
        echo -e "${YELLOW}Будет выполнено восстановление...${NC}\n"
        sleep 2
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
    echo -e "${YELLOW}Обнаружена прерванная установка на этапе: ${BOLD}${CURRENT_STEP}${NC}"
    echo -e "${YELLOW}Продолжаем с этого места...${NC}\n"
    sleep 2
fi

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

if [ -f "$NGINX_CONF_FILE" ] && [ "$CURRENT_STEP" == "start" ]; then
    echo -e "${YELLOW}Обнаружена существующая установка. Режим: ${BOLD}ОБНОВЛЕНИЕ${NC}"
    
    if [ ! -d "$PROJECT_DIR" ]; then
        echo -e "${YELLOW}⚠ Папка проекта '${PROJECT_DIR}' не найдена!${NC}"
        echo -e "${YELLOW}Восстанавливаем проект...${NC}\n"
        
        step_header "Восстановление проекта"
        run_silent "Клонирование репозитория" 3 git clone --depth 1 $REPO_URL
        
        if [ ! -d "$PROJECT_DIR" ]; then
            echo -e "${RED}${CROSS} Не удалось восстановить проект${NC}"
            echo -e "${YELLOW}Попробуйте:${NC}"
            echo -e "  1. Проверьте интернет: ping github.com"
            echo -e "  2. Удалите конфиг: sudo rm $NGINX_CONF_FILE"
            echo -e "  3. Запустите скрипт снова для полной установки"
            exit 1
        fi
    fi

    cd $PROJECT_DIR
    save_state "update_started"

    step_header "Обновление кода"
    if [ -d ".git" ]; then
        run_silent "Получение обновлений из Git" 3 bash -c 'git fetch --all && git reset --hard origin/main && git pull'
    else
        echo -e "  ${YELLOW}⚠ Git репозиторий повреждён, переклонирование...${NC}"
        cd ..
        sudo rm -rf "$PROJECT_DIR"
        run_silent "Клонирование репозитория" 3 git clone --depth 1 $REPO_URL
        cd $PROJECT_DIR
    fi
    save_state "code_updated"

    step_header "Проверка конфигурации"
    if update_nginx_config 2>/dev/null; then
        echo -e "  ${GREEN}${CHECK}${NC} Nginx конфиг обновлён"
    else
        echo -e "  ${GREEN}${CHECK}${NC} Nginx конфиг актуален"
    fi
    sudo mkdir -p /var/www/html 2>/dev/null || true
    if [ -f "src/shop_bot/webhook_server/static/502.html" ]; then
        sudo cp -f src/shop_bot/webhook_server/static/502.html /var/www/html/502.html
        echo -e "  ${GREEN}${CHECK}${NC} Страница 502 обновлена"
    else
        echo -e "  ${YELLOW}⚠ Файл 502.html не найден, пропускаем${NC}"
    fi
    save_state "config_updated"

    step_header "Перезапуск сервисов"
    run_docker
    save_state "completed"
    clear_state
    
    echo ""
    echo -e "${BOLD}${GREEN}╔════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${GREEN}║         🎉 Обновление завершено!                   ║${NC}"
    echo -e "${BOLD}${GREEN}╚════════════════════════════════════════════════════╝${NC}"
    echo ""
    exit 0
fi

echo -e "${YELLOW}Режим: ${BOLD}ПЕРВОНАЧАЛЬНАЯ УСТАНОВКА${NC}"

if [ "$CURRENT_STEP" == "start" ] || [ "$CURRENT_STEP" == "dependencies" ]; then
    step_header "Установка системных зависимостей"
    save_state "dependencies"

    install_package() {
        local cmd=$1
        local pkg=$2
        
        if ! command -v $cmd &> /dev/null; then
            echo -e "  ⠋ Установка $pkg..."
            
            sudo pkill -9 apt-get 2>/dev/null || true
            sudo pkill -9 apt 2>/dev/null || true
            sudo rm -f /var/lib/dpkg/lock* 2>/dev/null || true
            sudo dpkg --configure -a 2>/dev/null || true
            sleep 2
            
            if sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq 2>&1 | grep -v 'stable CLI interface' >/dev/null 2>&1; then
                if sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq -o Dpkg::Use-Pty=0 "$pkg" 2>&1 | grep -q "done\|Setting up"; then
                    echo -e "\r  ${GREEN}${CHECK}${NC} $pkg установлен             "
                else
                    echo -e "\r  ${YELLOW}⚠${NC} Проблема с $pkg, продолжаем...   "
                fi
            else
                echo -e "\r  ${YELLOW}⚠${NC} Не удалось обновить apt, продолжаем... "
            fi
        else
            echo -e "  ${GREEN}${CHECK}${NC} $cmd уже установлен"
        fi
    }

    install_package "git" "git"
    install_package "docker" "docker.io"
    install_package "nginx" "nginx"
    install_package "curl" "curl"
    install_package "certbot" "certbot"
    install_package "certbot-nginx" "python3-certbot-nginx"
    install_docker_compose

    for service in docker nginx; do
        if ! sudo systemctl is-active --quiet $service; then
            run_silent "Запуск $service" 2 bash -c "sudo systemctl start $service && sudo systemctl enable $service" || true
        fi
    done
    save_state "dependencies_done"
fi

if [ "$CURRENT_STEP" == "start" ] || [ "$CURRENT_STEP" == "dependencies_done" ] || [ "$CURRENT_STEP" == "clone" ]; then
    step_header "Подготовка проекта"
    save_state "clone"
    
    if [ ! -d "$PROJECT_DIR" ]; then
        run_silent "Клонирование репозитория" 3 git clone --depth 1 $REPO_URL
    else
        echo -e "  ${GREEN}${CHECK}${NC} Репозиторий уже существует"
    fi
    cd $PROJECT_DIR
    save_state "clone_done"
else
    cd $PROJECT_DIR 2>/dev/null || {
        echo -e "${RED}${CROSS} Не могу найти директорию проекта${NC}"
        clear_state
        exit 1
    }
fi

if [ "$CURRENT_STEP" == "start" ] || [ "$CURRENT_STEP" == "clone_done" ] || [ "$CURRENT_STEP" == "domain" ]; then
    step_header "Настройка домена"
    save_state "domain"
    echo ""
    
    USER_INPUT_DOMAIN=""
    EMAIL=""
    
    read_input "Введите домен (пример: vpn.example.com): " USER_INPUT_DOMAIN || {
        echo ""
        USER_INPUT_DOMAIN=""
    }
    
    if [ -z "$USER_INPUT_DOMAIN" ]; then
        USER_INPUT_DOMAIN="vpn.example.com"
        echo -e "  ${YELLOW}⚠ Используется домен: ${BOLD}${USER_INPUT_DOMAIN}${NC}"
    fi
    
    DOMAIN=$(echo "$USER_INPUT_DOMAIN" | sed -e 's%^https\?://%%' -e 's%/.*$%%' -e 's/[^a-zA-Z0-9.-]//g')
    
    read_input "Введите email для SSL (пример: admin@example.com): " EMAIL || {
        echo ""
        EMAIL=""
    }
    
    if [ -z "$EMAIL" ]; then
        EMAIL="admin@example.com"
        echo -e "  ${YELLOW}⚠ Используется email: ${BOLD}${EMAIL}${NC}"
    fi
    
    if ! echo "$EMAIL" | grep -qE '^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'; then
        echo -e "  ${YELLOW}⚠ Email некорректен, используется: admin@example.com${NC}"
        EMAIL="admin@example.com"
    fi
    
    echo -e "  ${GREEN}${CHECK}${NC} Домен: ${BOLD}${DOMAIN}${NC}"
    echo -e "  ${GREEN}${CHECK}${NC} Email: ${BOLD}${EMAIL}${NC}"
    save_state "domain_done" "{\"DOMAIN\":\"$DOMAIN\",\"EMAIL\":\"$EMAIL\"}"
else
    DOMAIN=$(get_state_data "DOMAIN")
    EMAIL=$(get_state_data "EMAIL")
    if [ -z "$DOMAIN" ]; then
        DOMAIN="vpn.example.com"
    fi
    if [ -z "$EMAIL" ]; then
        EMAIL="admin@example.com"
    fi
    echo -e "  ${GREEN}Используется домен: ${BOLD}${DOMAIN}${NC}"
fi

if [ "$CURRENT_STEP" == "start" ] || [ "$CURRENT_STEP" == "domain_done" ] || [ "$CURRENT_STEP" == "firewall" ]; then
    save_state "firewall"
    if command -v ufw &> /dev/null && sudo ufw status | grep -q 'Status: active'; then
        run_silent "Настройка firewall" 2 bash -c "
            sudo ufw allow 80/tcp 2>/dev/null || true &&
            sudo ufw allow 443/tcp 2>/dev/null || true &&
            sudo ufw allow 1488/tcp 2>/dev/null || true
        "
    fi
    save_state "firewall_done"
fi

if [ "$CURRENT_STEP" == "start" ] || [ "$CURRENT_STEP" == "firewall_done" ] || [ "$CURRENT_STEP" == "nginx" ]; then
    step_header "Настройка Nginx"
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

    run_silent "Проверка конфигурации Nginx" 2 bash -c "sudo nginx -t && sudo systemctl reload nginx"
    save_state "nginx_done"
fi

if [ "$CURRENT_STEP" == "start" ] || [ "$CURRENT_STEP" == "nginx_done" ] || [ "$CURRENT_STEP" == "ssl" ]; then
    step_header "Получение SSL-сертификата"
    save_state "ssl"
    
    if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
        echo -e "  ${GREEN}${CHECK}${NC} SSL-сертификат уже существует"
    else
        run_silent "Получение сертификата Let's Encrypt" 3 bash -c "
            sudo DEBIAN_FRONTEND=noninteractive certbot --nginx -d $DOMAIN --email $EMAIL --agree-tos --non-interactive --redirect --max-log-backups 0 --quiet
        " || true
    fi

    if [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
        echo -e "  ${RED}${CROSS} SSL-сертификат не найден!${NC}"
        echo -e "${YELLOW}Проверьте:${NC}"
        echo -e "  1. Домен $DOMAIN указывает на этот сервер"
        echo -e "  2. Порты 80 и 443 открыты"
        echo -e "  3. DNS записи обновлены"
        echo -e "\n${YELLOW}Продолжаю установку без SSL...${NC}"
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
    sudo cp -f src/shop_bot/webhook_server/static/502.html /var/www/html/502.html
    echo -e "  ${GREEN}${CHECK}${NC} Страница 502 установлена"

    run_silent "Применение SSL-конфигурации" 2 bash -c "sudo nginx -t && sudo systemctl reload nginx"
    save_state "final_config_done"
fi

if [ "$CURRENT_STEP" == "start" ] || [ "$CURRENT_STEP" == "final_config_done" ] || [ "$CURRENT_STEP" == "docker" ]; then
    step_header "Запуск приложения"
    save_state "docker"
    run_docker
    save_state "completed"
    clear_state
fi

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

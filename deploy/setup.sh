#!/usr/bin/env bash
# Install or update the UNN SUG E-Voting site on a fresh Ubuntu 24.04 server
# (written for Oracle Cloud Always Free, Ampere A1). Run as root:
#
#   curl -fsSL https://raw.githubusercontent.com/king-slay/SUG_VOTING_SITE/main/deploy/setup.sh -o setup.sh
#   sudo bash setup.sh
#
# Running it again updates the site to the latest code and keeps the database.
# The site is served at https://<public-ip-with-dashes>.sslip.io unless DOMAIN is set.
set -euo pipefail

REPO="${REPO:-https://github.com/king-slay/SUG_VOTING_SITE.git}"
BRANCH="${BRANCH:-main}"
ROOT=/srv/unnvote
APP="$ROOT/app"
ENV_FILE=/etc/unnvote.env
SERVICE_USER=unnvote

[ "$(id -u)" = 0 ] || { echo "Run with sudo: sudo bash setup.sh"; exit 1; }
export DEBIAN_FRONTEND=noninteractive

echo "==> Installing system packages"
apt-get update -q
apt-get install -y -q git python3-venv python3-dev build-essential pkg-config \
    default-libmysqlclient-dev mysql-server caddy curl iptables-persistent >/dev/null

echo "==> Opening ports 80 and 443 in the server firewall"
for port in 80 443; do
    iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
        || iptables -I INPUT 1 -p tcp --dport "$port" -j ACCEPT
done
netfilter-persistent save >/dev/null

id "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home "$ROOT" --shell /usr/sbin/nologin "$SERVICE_USER"
mkdir -p "$ROOT/media" "$ROOT/models"

echo "==> Fetching the code ($BRANCH)"
if [ -d "$APP/.git" ]; then
    git -C "$APP" fetch -q origin "$BRANCH"
    git -C "$APP" reset -q --hard "origin/$BRANCH"
else
    git clone -q --branch "$BRANCH" "$REPO" "$APP"
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "==> First install: creating the database and settings"
    PUBLIC_IP="$(curl -fsS https://api.ipify.org)"
    DOMAIN="${DOMAIN:-${PUBLIC_IP//./-}.sslip.io}"
    DB_PASSWORD="$(openssl rand -hex 24)"
    systemctl enable --now mysql >/dev/null
    mysql -uroot <<SQL
CREATE DATABASE IF NOT EXISTS unnvote CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'unnvote'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
ALTER USER 'unnvote'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
GRANT ALL ON unnvote.* TO 'unnvote'@'localhost';
SQL
    umask 077
    cat > "$ENV_FILE" <<CONF
DOMAIN=$DOMAIN
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=$(openssl rand -hex 32)
DJANGO_ALLOWED_HOSTS=$DOMAIN,$PUBLIC_IP,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://$DOMAIN
DJANGO_MEDIA_ROOT=$ROOT/media
MYSQL_DATABASE=unnvote
MYSQL_USER=unnvote
MYSQL_PASSWORD=$DB_PASSWORD
FACE_MODEL_DIR=$ROOT/models
DEEPFACE_HOME=$ROOT
CONF
    umask 022
fi
chgrp "$SERVICE_USER" "$ENV_FILE"; chmod 640 "$ENV_FILE"
DOMAIN="$(grep '^DOMAIN=' "$ENV_FILE" | cut -d= -f2)"

echo "==> Installing Python packages (the first time takes several minutes)"
[ -d "$ROOT/venv" ] || python3 -m venv "$ROOT/venv"
"$ROOT/venv/bin/pip" install -q --upgrade pip
"$ROOT/venv/bin/pip" install -q -r "$APP/requirements.txt"
chown -R "$SERVICE_USER:$SERVICE_USER" "$ROOT"

# Run manage.py as the service user with the production settings.
cat > /usr/local/bin/unnvote-manage <<'SH'
#!/usr/bin/env bash
set -a; . /etc/unnvote.env; set +a
cd /srv/unnvote/app
exec sudo -E -u unnvote /srv/unnvote/venv/bin/python manage.py "$@"
SH
chmod 755 /usr/local/bin/unnvote-manage

echo "==> Database migrations, static files, face models"
unnvote-manage migrate --noinput
unnvote-manage collectstatic --noinput -v0
sudo -u "$SERVICE_USER" bash -c "set -a; . $ENV_FILE; set +a; cd $APP; $ROOT/venv/bin/python -c 'import django; django.setup(); from voting import faces; faces.warm_up()'" \
    2>&1 | grep -E "Downloading|loaded" || true

echo "==> Web server"
cat > /etc/systemd/system/unnvote.service <<UNIT
[Unit]
Description=UNN SUG E-Voting (gunicorn)
After=network.target mysql.service

[Service]
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP
EnvironmentFile=$ENV_FILE
# One worker keeps a single copy of the face models in memory; threads serve voters in parallel.
ExecStart=$ROOT/venv/bin/gunicorn unnvote.wsgi --bind 127.0.0.1:8000 --workers 1 --threads 8 --timeout 120
Restart=always

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
	encode gzip
	request_body {
		max_size 20MB
	}
	handle_path /static/* {
		root * $APP/staticfiles
		file_server
	}
	handle {
		reverse_proxy 127.0.0.1:8000
	}
}
CADDY

systemctl daemon-reload
systemctl enable unnvote caddy >/dev/null
systemctl restart unnvote caddy

echo "==> Checking the site"
for _ in $(seq 1 30); do
    curl -fsS -o /dev/null "http://127.0.0.1:8000/" -H "Host: $DOMAIN" && break
    sleep 2
done
curl -fsS -o /dev/null "http://127.0.0.1:8000/" -H "Host: $DOMAIN" \
    && echo "App is running." || echo "App did not start: run  journalctl -u unnvote -n 50"

cat <<DONE

Done. The site is at:  https://$DOMAIN
(HTTPS can take a minute to appear the first time.)

First time only, create the committee account:
  sudo unnvote-manage createsuperuser

Update later to the newest code:  sudo bash setup.sh
DONE

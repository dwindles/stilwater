#!/usr/bin/env bash
# Installs or updates Stilwater Online on a Linux server over SSH (Python 3.10+, systemd, openssl,
# and nginx for the web services on port 80).
#   server/deploy.sh root@<server> -p <ssh port> -i <key>
# Open the game's ports in the server's firewall yourself:
#   ufw allow 80/tcp && ufw allow 27900/udp && ufw allow 27901/udp && ufw allow 28910/tcp && ufw allow 29900:29901/tcp
# The first run creates the AuthService key in /etc/stilwater-online and prints its public half,
# which the core needs (OnlineServer.cpp) and gamespy.AUTH_PUBLIC_KEY.
set -euo pipefail
target="$1"; shift
here="$(cd "$(dirname "$0")" && pwd)"

ssh "$@" "$target" 'mkdir -p /opt/stilwater-online'
scp -q "${@/#-p/-P}" "$here"/{main,gamespy,accounts,presence,master,natneg,notify,webservices,mods}.py \
    "$here/stilwater-online.service" "$here/nginx-stilwater-online.conf" "$here/nginx-holdonquietly-mods.conf" \
    "$target:/opt/stilwater-online/"
ssh "$@" "$target" '
    set -e
    id stilwater >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin stilwater
    install -d -o stilwater -g stilwater -m 750 /var/lib/stilwater-online
    # Shared mods files, which nginx serves (server/mods.py).
    install -d -o stilwater -g stilwater -m 755 /var/lib/stilwater-mods
    install -d -m 755 /etc/stilwater-online
    for key in authservice peerkey; do
        [ -f /etc/stilwater-online/$key.pem ] || openssl genrsa -traditional -out /etc/stilwater-online/$key.pem 1024 2>/dev/null
        chown root:stilwater /etc/stilwater-online/$key.pem
        chmod 640 /etc/stilwater-online/$key.pem
    done
    echo "AuthService public key: $(openssl rsa -in /etc/stilwater-online/authservice.pem -noout -modulus | cut -d= -f2 | tr A-F a-f)"
    mv /opt/stilwater-online/stilwater-online.service /etc/systemd/system/
    if [ -d /etc/nginx/sites-enabled ]; then
        mv /opt/stilwater-online/nginx-stilwater-online.conf /etc/nginx/sites-available/stilwater-online
        ln -sf /etc/nginx/sites-available/stilwater-online /etc/nginx/sites-enabled/stilwater-online
        # Shared mods live on holdonquietly.com (HTTPS) when this server hosts it.
        mv /opt/stilwater-online/nginx-holdonquietly-mods.conf /etc/nginx/snippets/stilwater-mods.conf
        site=/etc/nginx/conf.d/holdonquietly.conf
        if [ -f $site ] && ! grep -q "snippets/stilwater-mods.conf" $site; then
            cp $site /root/holdonquietly.conf.before-stilwater-mods
            sed -i "0,/server_name holdonquietly.com;/s//&\n    include snippets\/stilwater-mods.conf;/" $site
        fi
        if ! nginx -t -q; then
            [ -f /root/holdonquietly.conf.before-stilwater-mods ] && cp /root/holdonquietly.conf.before-stilwater-mods $site
            echo "nginx rejected the change; put back $site"
            exit 1
        fi
        systemctl reload nginx
    else
        echo "nginx not found: the web services (sign-in certificates) need port 80 passed to 127.0.0.1:29980"
    fi
    systemctl daemon-reload
    systemctl enable --quiet stilwater-online
    systemctl restart stilwater-online
    sleep 2
    systemctl is-active stilwater-online
    journalctl -u stilwater-online -n 5 --no-pager
'

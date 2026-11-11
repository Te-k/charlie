# Deploying Charlie

This guide sets up Charlie on a single Linux server (Debian 13 or Ubuntu 24.04+):

```
Internet ──HTTPS──▶ nginx ──HTTP (localhost:8001)──▶ gunicorn ──▶ Django ──▶ SQLite
                     ├─ TLS certificates (Let's Encrypt)
                     ├─ serves /static/ directly
                     └─ rate-limits the login page
```

A single server with SQLite is plenty for a reading list maintained by a few people. All production
settings are environment variables read by `charlie/settings.py`. Nothing in the code needs to be
changed to deploy.

Paths used below (adapt them if you like):

| Path | Content | Owner / mode |
|---|---|---|
| `/srv/charlie/` | the code and its virtualenv | `root:root`, not writable by the app |
| `/var/lib/charlie/` | the SQLite database | `charlie:charlie`, `750` |
| `/var/www/charlie/static/` | collected static files | `root:root`, readable by nginx |
| `/etc/charlie/charlie.env` | secrets and settings | `root:charlie`, `640` |

---

## 1. Prepare the server

```sh
sudo apt update && sudo apt install -y python3 python3-venv nginx certbot python3-certbot-nginx sqlite3 git
# Python 3.13 or newer is required (Django 6). Check with: python3 --version

sudo adduser --system --group --home /var/lib/charlie --shell /usr/sbin/nologin charlie
sudo install -d -o charlie -g charlie -m 750 /var/lib/charlie
sudo install -d -o root -g charlie -m 750 /etc/charlie
sudo install -d -m 755 /var/www/charlie/static
```

Point your domain's DNS (A/AAAA records) to the server, and open only ports 22, 80 and 443:

```sh
sudo apt install -y ufw
sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable
```

## 2. Install the code

```sh
sudo git clone <your repository> /srv/charlie        # or copy the project with rsync
cd /srv/charlie
sudo python3 -m venv .venv
sudo .venv/bin/pip install --upgrade pip
sudo .venv/bin/pip install -r requirements.txt        # not requirements-dev.txt
```

Don't copy your development `db.sqlite3` or `.venv` to the server. The compiled stylesheet
(`articles/static/articles/app.css`) is part of the project, so no Node or Tailwind is needed on the
server.

## 3. Configure the environment

Generate a secret key:

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Create `/etc/charlie/charlie.env`:

```sh
sudo install -m 640 -o root -g charlie /dev/null /etc/charlie/charlie.env
sudo editor /etc/charlie/charlie.env
```

```ini
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=<the generated key>
DJANGO_ALLOWED_HOSTS=articles.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://articles.example.com
DJANGO_DB_PATH=/var/lib/charlie/db.sqlite3
DJANGO_STATIC_ROOT=/var/www/charlie/static
DJANGO_ADMIN_URL=<something hard to guess, e.g. manage-k3x9q>
```

All variables:

| Variable | Default | Production value |
|---|---|---|
| `DJANGO_DEBUG` | `1` | **`0`**. Never run with debug on: it shows code and settings on errors. |
| `DJANGO_SECRET_KEY` | development key | **Required.** At least 50 random characters. The app refuses to start without it when debug is off. Keep it private; changing it logs everyone out. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Your domain(s), comma-separated. Requests for any other host are rejected. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | (empty) | `https://` + your domain(s), comma-separated. |
| `DJANGO_DB_PATH` | `./db.sqlite3` | `/var/lib/charlie/db.sqlite3` |
| `DJANGO_STATIC_ROOT` | `./staticfiles` | `/var/www/charlie/static` |
| `DJANGO_ADMIN_URL` | `admin/` | A hard-to-guess path. `/admin/` then returns 404. |
| `DJANGO_SECURE_SSL_REDIRECT` | `1` | Keep `1`. Django redirects HTTP to HTTPS as well as nginx. |
| `DJANGO_HSTS_SECONDS` | `31536000` (1 year) | Browsers then refuse plain HTTP for this domain for that long. Use `300` for the first deployment, then raise it once HTTPS works. |
| `DJANGO_HSTS_INCLUDE_SUBDOMAINS` | `0` | `1` only if **every** subdomain of the domain is served over HTTPS. |
| `DJANGO_HSTS_PRELOAD` | `0` | `1` only if you submit the domain to hstspreload.org. Hard to undo. |
| `DJANGO_LOG_LEVEL` | `INFO` | `INFO` or `WARNING`. |

When debug is off, the settings also turn on:
- secure (HTTPS-only) session and CSRF cookies,
- HSTS,
- trust in the `X-Forwarded-Proto` header from nginx.

Whatever the debug setting, every response gets:
- `X-Frame-Options: DENY`,
- `X-Content-Type-Options: nosniff`,
- `Referrer-Policy: same-origin`,
- a strict **Content-Security-Policy**: scripts and styles only from the site itself, no inline
  scripts, images from any HTTPS site (article photos are loaded from their original websites).

To run `manage.py` commands as the app user with this environment, create the helper
`/usr/local/bin/charlie-manage`:

```sh
sudo tee /usr/local/bin/charlie-manage >/dev/null <<'EOF'
#!/bin/sh
# Run a Django management command as the charlie user with the production environment.
exec sudo -u charlie sh -c 'set -a; . /etc/charlie/charlie.env; set +a; cd /srv/charlie && exec .venv/bin/python manage.py "$@"' -- "$@"
EOF
sudo chmod 755 /usr/local/bin/charlie-manage
```

## 4. Initialise the application

```sh
sudo charlie-manage check --deploy     # must not report errors (see the HSTS note below)
sudo charlie-manage migrate            # creates the database and loads the countries
sudo sh -c 'set -a; . /etc/charlie/charlie.env; set +a; cd /srv/charlie && .venv/bin/python manage.py collectstatic --noinput'
sudo charlie-manage createsuperuser    # use a strong, unique password
sudo chmod 640 /var/lib/charlie/db.sqlite3
```

`check --deploy` warns about `SECURE_HSTS_INCLUDE_SUBDOMAINS` and `SECURE_HSTS_PRELOAD` unless you
turned them on. These are deliberate opt-ins (see the table above).

`collectstatic` runs as root because the app user must not be able to write the static files.

There is no registration page. Create every account yourself:
- with `charlie-manage createsuperuser` for administrators,
- in the admin for other users.

Give **staff** status only to the people who may see the Mastodon and Bluesky credentials and change
the website name at `/settings/`.

## 5. Run gunicorn with systemd

`/etc/systemd/system/charlie.service`:

```ini
[Unit]
Description=Charlie (gunicorn)
After=network.target

[Service]
Type=notify
User=charlie
Group=charlie
WorkingDirectory=/srv/charlie
EnvironmentFile=/etc/charlie/charlie.env
# 3 workers suits a small server; a request can take up to about a minute (it fetches a page,
# then posts to Mastodon and Bluesky), hence the long timeout.
ExecStart=/srv/charlie/.venv/bin/gunicorn charlie.wsgi \
    --bind 127.0.0.1:8001 --workers 3 --timeout 90 \
    --access-logfile - --error-logfile -
ExecReload=/bin/kill -s HUP $MAINPID
Restart=on-failure

# Sandboxing: the app can only write to its data directory.
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/charlie
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=true
LockPersonality=true
RestrictRealtime=true
SystemCallArchitectures=native
CapabilityBoundingSet=
UMask=0027

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now charlie
sudo systemctl status charlie
journalctl -u charlie -f            # logs
```

gunicorn listens on `127.0.0.1` only, so it can't be reached from outside except through nginx.

## 6. nginx and HTTPS

`/etc/nginx/sites-available/charlie`:

```nginx
# At most 10 login attempts per minute per IP address (stops password guessing).
limit_req_zone $binary_remote_addr zone=charlie_login:10m rate=10r/m;

server {
    listen 80;
    listen [::]:80;
    server_name articles.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name articles.example.com;

    # Filled in by certbot (step below).
    # ssl_certificate     /etc/letsencrypt/live/articles.example.com/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/articles.example.com/privkey.pem;

    server_tokens off;
    client_max_body_size 1m;   # the app only receives small forms

    location /static/ {
        alias /var/www/charlie/static/;
        expires 7d;
        add_header Cache-Control "public";
        add_header X-Content-Type-Options "nosniff";
    }

    location = /login/ {
        limit_req zone=charlie_login burst=5 nodelay;
        include /etc/nginx/snippets/charlie-proxy.conf;
    }

    location / {
        include /etc/nginx/snippets/charlie-proxy.conf;
    }
}
```

`/etc/nginx/snippets/charlie-proxy.conf`:

```nginx
proxy_pass http://127.0.0.1:8001;
proxy_set_header Host $host;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_read_timeout 90s;
proxy_redirect off;
```

Use the same rate limit for the admin login if you like, with
`location = /<DJANGO_ADMIN_URL>login/`.

Enable the site and get a certificate:

```sh
sudo ln -s /etc/nginx/sites-available/charlie /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d articles.example.com     # also sets up automatic renewal
sudo certbot renew --dry-run
```

**Important:** nginx must set `X-Forwarded-Proto` to the real scheme. Django trusts this header to
know the request was HTTPS. Never expose gunicorn directly, or anyone could fake the header.

### Check the result

```sh
curl -sI http://articles.example.com/  | head -3      # 301 to https://
curl -sI https://articles.example.com/ | grep -iE "strict-transport|content-security|x-frame"
curl -s -o /dev/null -w "%{http_code}\n" https://articles.example.com/admin/   # 404
```

You can also test with https://observatory.mozilla.org and https://www.ssllabs.com/ssltest/.

## 7. Mastodon and Bluesky

Configure them after logging in, at **Settings** (`/settings/`, staff only). Use credentials with
the least power possible:
- **Mastodon**: create an application under Preferences → Development with only the
  `write:statuses` scope.
- **Bluesky**: create an **app password** (Settings → Privacy and security → App passwords). Never
  use the account's main password.

The tokens are stored in plain text in the database. This is one more reason the database file and
its backups must stay private. If the server or a backup is compromised, revoke the token and the
app password from the Mastodon and Bluesky settings.

The server needs outgoing HTTPS access: it fetches article pages and images, and calls the
Mastodon and Bluesky APIs. The page fetcher refuses private and local addresses (including after
redirects), so users can't make it reach internal services.

## 8. Backups

Everything worth keeping is in the SQLite database (`/var/lib/charlie/db.sqlite3`). Back it up with
SQLite's online backup, which is safe while the app runs. Don't use a plain `cp`.

`/etc/cron.daily/charlie-backup`:

```sh
#!/bin/sh
set -e
umask 077
dest=/var/backups/charlie
mkdir -p "$dest"
sqlite3 /var/lib/charlie/db.sqlite3 ".backup '$dest/db-$(date +%F).sqlite3'"
find "$dest" -name 'db-*.sqlite3' -mtime +30 -delete
```

```sh
sudo chmod 700 /etc/cron.daily/charlie-backup
```

Copy the backups off the server, and encrypt them because they contain the social media tokens.
Test a restore from time to time: stop the service, copy a backup to `/var/lib/charlie/db.sqlite3`
(owner `charlie`, mode `640`), and start the service again.

## 9. Updating

```sh
cd /srv/charlie
sudo cp /var/lib/charlie/db.sqlite3 /var/backups/charlie/db-before-update.sqlite3
sudo git pull
sudo .venv/bin/pip install -r requirements.txt
sudo charlie-manage migrate
sudo sh -c 'set -a; . /etc/charlie/charlie.env; set +a; .venv/bin/python manage.py collectstatic --noinput'
sudo charlie-manage check --deploy
sudo systemctl reload charlie        # graceful: finishes running requests first
```

Keep the system patched (`unattended-upgrades` on Debian/Ubuntu). To find dependency updates with
known vulnerabilities, run `pip list --outdated` and
`pip install pip-audit && pip-audit -r requirements.txt` regularly.

## Security checklist

- [ ] `DJANGO_DEBUG=0`, and a long random `DJANGO_SECRET_KEY` that is in no repository.
- [ ] `/etc/charlie/charlie.env` is `640 root:charlie`; the database is `640 charlie:charlie`.
- [ ] The code and static files aren't writable by the `charlie` user.
- [ ] gunicorn listens on `127.0.0.1` only; the firewall allows only 22, 80 and 443.
- [ ] HTTPS works, HTTP redirects to it, and the certificate renews automatically.
- [ ] `charlie-manage check --deploy` shows no errors.
- [ ] The admin is at a custom `DJANGO_ADMIN_URL`; staff status is given only to people who need it.
- [ ] All accounts have strong, unique passwords.
- [ ] Mastodon uses a `write:statuses`-only token; Bluesky uses an app password.
- [ ] Daily backups, stored encrypted off the server, and a restore has been tested.
- [ ] System and Python packages are updated regularly.

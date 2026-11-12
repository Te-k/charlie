# Charlie

A small Django + [Tailwind CSS](https://tailwindcss.com/) app to keep track of interesting articles.

- Articles have a URL, title, description, photo, tags, and optionally countries and organizations.
- Each article has a language (English by default). The languages offered are set on the Settings
  page.
- Each article is linked to its publisher, found from the URL's domain. Publishers are created
  automatically and can be given a description and an alternative website.
- Adding an article takes two steps: paste the URL, and the app fetches the title, description and photo
  (OpenGraph / Twitter card / `<title>` / meta description); then check and edit them before saving.
  `/articles/add/?url=…` goes straight to the second step (handy for a bookmarklet).
- Staff users can change the website name at `/settings/` (shown in the header, browser tabs and RSS feeds).
- New articles can be posted automatically on Mastodon and Bluesky. Staff users set up the accounts
  and the message formats at `/settings/`. Articles can also be posted later from their page.
- The home page lists articles from newest to oldest, 20 per page. There are pages per tag, organization, publisher and country.
- RSS feeds: `/feed/` (all articles), `/tags/<slug>/feed/`, `/organizations/<slug>/feed/`, `/publishers/<slug>/feed/`, `/countries/<code>/feed/`.
- Anyone can read. Adding articles, tags and organizations needs a login. There is no registration page:
  you create users from the command line or in the Django admin.

## Setup

```sh
uv venv && uv pip install -r requirements.txt   # or: python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate               # also loads the list of countries
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

Run the tests with `.venv/bin/python manage.py test articles`.

## Styles

The compiled stylesheet `articles/static/articles/app.css` is part of the project, so running the app
needs no build tools. After changing classes in templates, rebuild it from `assets/tailwind.css`:

```sh
uv pip install -r requirements-dev.txt
.venv/bin/tailwindcss -i assets/tailwind.css -o articles/static/articles/app.css --minify   # add --watch while editing
```

## Mastodon and Bluesky

- **Mastodon**: in your account, go to Preferences → Development → New application, give it the
  `write:statuses` scope, and paste the access token in Settings.
- **Bluesky**: create an app password (Settings → Privacy and security → App passwords) and use it
  with your handle. Don't use your main password.

The tokens are stored in the database as plain text, so protect the database accordingly.

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for a secure production setup (nginx, gunicorn, systemd,
HTTPS, backups) and the full list of environment variables.

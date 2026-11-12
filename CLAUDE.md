# CLAUDE.md

Charlie is a Django app for keeping track of interesting articles. Each article has a URL, title,
description and photo, a publisher, and can be linked to tags, countries and organizations. Anyone can read the
site and subscribe by RSS. Logged-in users add, edit and delete content. New articles can be posted
to Mastodon and Bluesky. The user-facing description is in `README.md`.

## Commands

Use the Makefile (`make help` lists the targets):

```sh
make install          # create .venv (Python 3.14) and install requirements-dev.txt
make runserver        # migrate, then run the dev server (HOST=, PORT= to override)
make test             # all tests; ARGS=social to run one app
make lint             # ruff check + ruff format --check + Django checks + missing migrations
make format           # ruff format + ruff check --fix
make css / css-watch  # rebuild the Tailwind stylesheet
make check            # lint + test: run before committing
make deploy-check     # Django's production checks (expect only the two HSTS opt-in warnings)
.venv/bin/python manage.py createsuperuser             # the only way to get an account
.venv/bin/python manage.py makemigrations <app>        # after any model change
```

`make lint` must pass. Ruff is configured in `pyproject.toml` (line length 100; migrations excluded).

**After changing Tailwind classes in templates, Python or `app.js`, run `make css`**
(or `make css-watch` while working). The compiled `articles/static/articles/app.css` is part of the
project, so the running app never needs Node or a build step. A class that wasn't there at the last
build does nothing.

Dependencies: Django 6, requests, beautifulsoup4, and django-countries (used only for its data, by
the countries migration; it is not in `INSTALLED_APPS`). Dev only: pytailwindcss, which provides the
standalone Tailwind v4 CLI.

## Layout

- `charlie/`: project settings and root URLs. Login and logout use Django's auth views at `/login/`
  and `/logout/`.
- `articles/`: the main app.
  - `models.py`: `Article`, plus `Tag`, `Organization` and `Publisher` (all use `SluggedModel`,
    which builds a unique slug automatically), `Country` (ISO code, `flag` emoji property), and `SiteSettings`
    (a single row: website name and description, article languages; read the name with
    `site_name()`).
  - `metadata.py`: fetches a page's title, description and image (OpenGraph, then Twitter card,
    then `<title>` / meta description), and downloads images (`fetch_image`).
    The publication date (`published_on`) comes from `article:published_time`, JSON-LD
    `datePublished`, `<time>` tags, then generic date meta tags; `parse_date()` rejects
    implausible dates.
  - `views.py`: list pages, detail page, the two-step add flow, edit, delete, and adding tags and
    organizations.
  - `feeds.py`: RSS feeds (`/feed/`, plus one per tag, organization, publisher and country).
  - `context_processors.py`: puts `site_name` into every template.
  - `templatetags/articles_tags.py`: `day_label` and `is_relative_day`, used to group the home page
    by day.
- `social/`: posting to Mastodon and Bluesky.
  - `models.py`: `SocialSettings` (a single row with credentials, message formats and defaults)
    and `SocialPost` (one row per post made about an article).
  - `publishers.py`: builds messages from templates and calls the Mastodon and Bluesky APIs. It
    does no Django request handling.
  - `views.py`: `SettingsView` at `/settings/` (staff only; it saves the `SiteSettingsForm` and the
    `SocialSettingsForm` together) and `share` (POST, posts an existing article).
  - `templatetags/social_tags.py`: `{% article_social article %}`, the box on the article page
    listing posts and showing "Post on …" buttons.
- `templates/`: `base.html` (layout, nav, messages) and `registration/login.html`. App templates
  live in `<app>/templates/<app>/`.
- `assets/tailwind.css`: the Tailwind source (theme colours, component classes).
- `articles/static/articles/app.js`: all of the site's JavaScript (see "No inline JavaScript").
- `DEPLOYMENT.md`: production setup (nginx, gunicorn, systemd, backups). Keep it up to date when
  you add environment variables, services or outgoing network calls.

## How things work

### Adding an article (two steps, nothing saved before review)
1. `GET /articles/add/` shows `article_add_url.html`, a URL-only form (`ArticleUrlForm`). It
   refuses URLs that are already stored and links to the existing article.
2. POST with `action=fetch`. `ArticleFormMixin.fetch_and_review()` calls
   `articles.metadata.fetch_metadata()`, writes the results into a copy of the POST data, and shows
   a **bound** `ArticleForm` in `article_form.html`. Nothing is saved.
3. POST with `action=save` (or no action) saves normally. Metadata is **never** fetched on save.

The add form uses `ArticleCreateForm`, which adds `created_at` ("Added on", pre-filled with the
current time by `step_one()`, empty means now, future dates refused). The edit form doesn't offer it.

`/articles/add/?url=…` skips step 1. On the edit form, "Fetch details again" also posts
`action=fetch`; it overwrites the title, description and image in the form without saving.

### Languages
- `Article.language` is a language code (default `en`). The codes offered come from
  `SiteSettings.languages` (a JSON list) and `default_language`, edited on the Settings page; the
  full list is Django's `global_settings.LANGUAGES` (`ALL_LANGUAGES`).
- `ArticleForm` builds the `language` choices at runtime and keeps an article's current language
  selectable even after it is removed from the list. Empty means the default.
- Pages show `article.language_name` and set `lang=` on the title and description. Lists only label
  articles whose language differs from the default (`default_language` is in every template's
  context).

### Publishers (found from the article's domain)
- `Publisher` has `website` and an optional `alternative_website`. `save()` stores their normalised
  domains (lowercase, no `www.`, see `url_domain()`) in `domain` / `alternative_domain` for lookups.
- `Publisher.objects.for_url(url)` matches the URL's domain against both fields. Subdomains match
  (`blog.example.com` belongs to `example.com`) and the most specific domain wins.
- `Article.save()` sets the publisher when it is empty, creating one with
  `get_or_create_for_url()`. The new publisher is named from `article.publisher_name` (the page's
  `og:site_name`, carried through the review step in a hidden form field), else the domain.
- The review step pre-selects the matching publisher, or tells the user that a new one will be
  created (`new_publisher` in the context). Nothing is created before saving.
- On save, if the URL changed but the publisher field didn't, the publisher is found again.
- `PublisherForm` refuses a domain that already belongs to another publisher, so lookups stay
  unambiguous. Editing a publisher's websites does not relink existing articles.
- Migration `0006` linked articles that existed before publishers were added.

### Posting to Mastodon / Bluesky
- `social.forms.add_publish_fields()` adds `post_mastodon` / `post_bluesky` checkboxes, **only
  for networks where `SocialSettings.is_ready(network)` is true** (enabled and credentials filled
  in). This happens only on the add form (`ArticleCreateView.extend_form`), not on edit.
- Whether the boxes start ticked comes from `<network>_default`. `step_one()` puts that value into
  the data passed to the review step.
- After saving, `ArticleCreateView.after_save()` calls `social.views.publish_with_messages()`. A
  failed post shows an error message but never stops the article from being saved. The article
  page offers "Post on …" to retry.
- `publishers.publish()` picks `mastodon_post` or `bluesky_post` **at call time** (not from a dict
  built at import time) so tests can mock them. Keep it that way.
- Message templates use `{placeholder}` replaced by a regex (`publishers.fill`). Never use
  `str.format`: it would allow attribute access such as `{title.__class__}`. To add a placeholder,
  add it to `PLACEHOLDERS` and to `build_context()`.
- Length limits: Mastodon 500 characters, with every URL counting as 23; Bluesky 300.
  `render_message()` shortens the description first, then the title.
- Bluesky: create a session with the handle and app password, optionally upload the thumbnail with
  `uploadBlob` (at most 1 MB), then `createRecord`. Links and hashtags need **facets**, which use
  **UTF-8 byte offsets**, not character positions. The post URL is built from the returned `at://`
  URI.
- Secret fields (`mastodon_access_token`, `bluesky_app_password`) are never sent back to the
  browser. Submitting them empty keeps the saved value. They are stored as plain text in the
  database.

### Fetching pages safely
`metadata._get()` follows redirects itself and refuses any host that doesn't resolve to a public IP
address (`_is_public_host`), at every hop. This stops users from making the server fetch internal
addresses. Every outgoing request for a user-supplied URL (pages, images) must go through
`_get()`. Calls to the Mastodon instance or Bluesky service set by staff use `requests` directly.

### Permissions
- Reading pages and feeds: anyone.
- Adding, editing and deleting articles, adding tags and organizations, and adding and editing
  publishers: any logged-in user
  (`LoginRequiredMixin`). Any user can edit any article, not just their own.
- `/settings/` (website name, social accounts): `is_staff` only.
- The site never shows **who added an article** or who posted it to social networks.
  `Article.added_by` and `SocialPost.posted_by` are still recorded, and visible only in the admin.
- There is deliberately **no registration**. Users are created with `createsuperuser` or in
  `/admin/`. Don't add sign-up pages.

## Conventions

- **Views**: class-based. List pages filtered by tag, organization, publisher or country share
  `FilteredArticleListView` (`model`, `relation`, `kind`, `lookup`); feeds mirror this with
  `_FilteredFeed`. Countries are looked up by lowercase ISO code in URLs and stored uppercase.
- **Single-row settings** (`SiteSettings`, `SocialSettings`): `save()` forces `pk=1`; read with
  `.load()`. Add new site-wide options as fields on these models and to the Settings page, rather
  than as new settings models or entries in `settings.py`.
- **Querysets**: use `Article.objects.with_relations()` in lists to avoid extra queries per article.
  Articles are ordered `-created_at`; pagination size is `settings.ARTICLES_PER_PAGE` (20).
- **Forms in templates**: render fields with `{% include "articles/_form_field.html" with field=… %}`.
  It handles labels, checkboxes, help text and errors. Styling comes from the `.field` CSS
  component, so widgets need no CSS classes.
- **Styling** (Tailwind v4, see `assets/tailwind.css`):
  - Use the theme colours `paper`, `surface`, `ink`, `muted`, `line`, `accent`, `accent-ink` and
    `accent-soft` (e.g. `bg-surface text-muted`). They switch automatically in dark mode, so
    `dark:` variants are rarely needed. Avoid raw greys.
  - Component classes: `card`; `btn-primary`, `btn-secondary`, `btn-ghost`, `btn-danger`, plus
    `btn-sm`; `field`, `input`, `help`, `error`; `chip-tag`, `chip-plain`; `eyebrow`; `prose-link`.
  - Tailwind v4 can't `@apply` a custom class inside another one, so shared styles use grouped
    selectors (`.btn, .btn-primary, … {}`).
  - Headings use `font-serif`. Page headers follow the pattern: eyebrow, then a big serif `h1`,
    then `border-b-2 border-ink`.
  - `aria-busy="true"` shows a spinner. Give submit buttons that start slow network calls the
    `data-busy` attribute.
- **No inline JavaScript or CSS.** `SECURE_CSP` in `settings.py` (Django's built-in CSP, enforced
  in development too) allows scripts and styles only from the site itself. So:
  - no `onclick=` / `onerror=` / `style=` attributes, `<script>` blocks or `javascript:` links;
  - add behaviour to `app.js` through `data-` attributes and listeners on `document`;
  - existing hooks: `data-busy` (spinner on click), `data-fallback="remove|remove-parent|message"`
    (broken images), `data-filter` with `data-name` on items (list filter).

  `app.js` is loaded in `<head>` without `defer` so its image-error listener is in place before
  images load.
- **Remote images** are always shown with `referrerpolicy="no-referrer"` and a `data-fallback`.
- **Messages**: report results with `django.contrib.messages`. `base.html` colours them by level
  and turns URLs into links.
- **Text**: user-facing text is short, plain English.

## Testing

- Tests live in `articles/tests/` and `social/tests/`. **Never make real network calls in tests.**
  Mock `articles.metadata.fetch_metadata`, `social.publishers.requests.get` / `.post`,
  `social.publishers.fetch_image`, or `social.publishers.mastodon_post` / `bluesky_post`.
- The countries migration runs in the test database, so `Country.objects.get(code="FR")` works.
- Tests that post to `/settings/` must include `site-site_name` (the site form uses the `site`
  prefix) as well as the social fields.
- To check the UI by hand, run the dev server and log in. Headless Chromium is at
  `/usr/bin/chromium` if you need screenshots. Delete any test users or data you create in the
  development database (`db.sqlite3`), which holds the owner's real data.

## Production

See `DEPLOYMENT.md`. All production settings are environment variables (`DJANGO_DEBUG`,
`DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DJANGO_DB_PATH`,
`DJANGO_STATIC_ROOT`, `DJANGO_ADMIN_URL`, `DJANGO_HSTS_*`, `DJANGO_SECURE_SSL_REDIRECT`,
`DJANGO_LOG_LEVEL`), read with the `env_bool` / `env_list` helpers in `settings.py`.
- With `DEBUG` off, the app **refuses to start** unless the secret key is set and at least 50
  characters long, and it turns on secure cookies, HSTS and the HTTPS redirect.
- It expects nginx in front, setting `X-Forwarded-Proto`.
- The admin URL comes from `settings.ADMIN_URL`. Never hard-code `/admin/`; use
  `{% url 'admin:index' %}`.
- Don't add email features without configuring a real email backend: none is set up, because the
  app sends no email.

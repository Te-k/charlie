"""Build messages from templates and publish them on Mastodon and Bluesky."""

import logging
import re
import uuid
from datetime import UTC, datetime

import requests

from articles.metadata import fetch_image

from .models import SocialPost

logger = logging.getLogger(__name__)

TIMEOUT = 20
LIMITS = {"mastodon": 500, "bluesky": 300}
MASTODON_URL_LENGTH = 23  # Mastodon counts every link as 23 characters
BLUESKY_THUMB_MAX_BYTES = 1_000_000

PLACEHOLDERS = {
    "title": "Article title",
    "description": "Article description (shortened to fit)",
    "url": "Article URL",
    "link": "Link to the article page on this site",
    "domain": "Website of the article, e.g. example.com",
    "publisher": "Publisher name, e.g. Le Monde (the domain if there is none)",
    "tags": "Tags as hashtags, e.g. #MachineLearning #Privacy",
    "organizations": "Organization names, comma-separated",
    "countries": "Country names, comma-separated",
}

URL_RE = re.compile(r"https?://[^\s<>\"]+")
HASHTAG_RE = re.compile(r"(?<![\w#])#(\w+)")
PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


class PublishError(Exception):
    pass


# --------------------------------------------------------------------- messages


def hashtag(name):
    words = re.findall(r"\w+", name)
    if not words:
        return ""
    if len(words) == 1:
        return f"#{words[0]}"
    return "#" + "".join(w[:1].upper() + w[1:] for w in words)


def build_context(article, link=""):
    if article.pk:
        tags = [t.name for t in article.tags.all()]
        organizations = [c.name for c in article.organizations.all()]
        countries = [c.name for c in article.countries.all()]
    else:  # unsaved example article (settings preview)
        tags = getattr(article, "example_tags", [])
        organizations = getattr(article, "example_organizations", [])
        countries = getattr(article, "example_countries", [])
    return {
        "title": article.title or article.url,
        "description": article.description,
        "url": article.url,
        "link": link,
        "domain": article.domain,
        "publisher": article.publisher.name if article.publisher else article.domain,
        "tags": " ".join(filter(None, (hashtag(t) for t in tags))),
        "organizations": ", ".join(organizations),
        "countries": ", ".join(countries),
    }


def fill(template, context):
    text = PLACEHOLDER_RE.sub(
        lambda m: context.get(m.group(1), m.group(0)), template.replace("\r\n", "\n")
    )
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def text_length(text, network):
    if network == "mastodon":
        return len(URL_RE.sub("x" * MASTODON_URL_LENGTH, text))
    return len(text)


def _shorten(value, room):
    if room <= 1:
        return ""
    if len(value) <= room:
        return value
    return value[: room - 1].rstrip() + "…"


def render_message(template, context, network):
    """Fill the template; shorten the description, then the title, to fit the limit."""
    limit = LIMITS[network]
    context = dict(context)
    text = fill(template, context)
    for key in ("description", "title"):
        if text_length(text, network) <= limit:
            return text
        # Measure with a 1-char stand-in so surrounding blank lines are kept.
        without = text_length(fill(template, {**context, key: "x"}), network) - 1
        context[key] = _shorten(context[key], limit - without)
        text = fill(template, context)
    if text_length(text, network) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


# --------------------------------------------------------------------- Mastodon


def _error_message(response):
    try:
        data = response.json()
        detail = data.get("error_description") or data.get("error") or data.get("message")
    except ValueError:
        detail = None
    return f"HTTP {response.status_code}" + (f": {detail}" if detail else "")


def _mastodon_api(config, path):
    return config.mastodon_instance.rstrip("/") + path


def mastodon_check(config):
    try:
        r = requests.get(
            _mastodon_api(config, "/api/v1/accounts/verify_credentials"),
            headers={"Authorization": f"Bearer {config.mastodon_access_token}"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise PublishError(f"Mastodon: {exc}") from exc
    if not r.ok:
        raise PublishError(f"Mastodon: {_error_message(r)}")
    return "@" + r.json().get("acct", "?")


def mastodon_post(config, text, article):
    try:
        r = requests.post(
            _mastodon_api(config, "/api/v1/statuses"),
            headers={
                "Authorization": f"Bearer {config.mastodon_access_token}",
                "Idempotency-Key": str(uuid.uuid4()),
            },
            data={"status": text, "visibility": config.mastodon_visibility},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise PublishError(f"Mastodon: {exc}") from exc
    if not r.ok:
        raise PublishError(f"Mastodon: {_error_message(r)}")
    data = r.json()
    return data.get("url") or data.get("uri", ""), str(data.get("id", ""))


# ---------------------------------------------------------------------- Bluesky


def _bsky(config, method):
    return f"{config.bluesky_service.rstrip('/')}/xrpc/{method}"


def bluesky_session(config):
    try:
        r = requests.post(
            _bsky(config, "com.atproto.server.createSession"),
            json={
                "identifier": config.bluesky_handle.lstrip("@"),
                "password": config.bluesky_app_password,
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise PublishError(f"Bluesky: {exc}") from exc
    if not r.ok:
        raise PublishError(f"Bluesky: {_error_message(r)}")
    return r.json()


def bluesky_check(config):
    return "@" + bluesky_session(config).get("handle", config.bluesky_handle)


def _byte_span(text, start, end):
    return {
        "byteStart": len(text[:start].encode()),
        "byteEnd": len(text[:end].encode()),
    }


def bluesky_facets(text):
    """Rich-text facets so links and hashtags are clickable on Bluesky."""
    facets, url_spans = [], []
    for m in URL_RE.finditer(text):
        url = m.group().rstrip(".,;:!?)'\"")
        start, end = m.start(), m.start() + len(url)
        url_spans.append((start, end))
        facets.append(
            {
                "index": _byte_span(text, start, end),
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
            }
        )
    for m in HASHTAG_RE.finditer(text):
        if any(s <= m.start() < e for s, e in url_spans):
            continue
        facets.append(
            {
                "index": _byte_span(text, m.start(), m.end()),
                "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": m.group(1)}],
            }
        )
    return facets


def _bluesky_thumb(config, session, image_url):
    image = fetch_image(image_url, max_bytes=BLUESKY_THUMB_MAX_BYTES)
    if not image:
        return None
    content, content_type = image
    try:
        r = requests.post(
            _bsky(config, "com.atproto.repo.uploadBlob"),
            headers={
                "Authorization": f"Bearer {session['accessJwt']}",
                "Content-Type": content_type,
            },
            data=content,
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        return None
    return r.json().get("blob") if r.ok else None


def bluesky_post(config, text, article):
    session = bluesky_session(config)
    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    facets = bluesky_facets(text)
    if facets:
        record["facets"] = facets
    if config.bluesky_link_card:
        external = {
            "uri": article.url,
            "title": article.title or article.url,
            "description": (article.description or "")[:1000],
        }
        if article.image_url:
            thumb = _bluesky_thumb(config, session, article.image_url)
            if thumb:
                external["thumb"] = thumb
        record["embed"] = {"$type": "app.bsky.embed.external", "external": external}
    try:
        r = requests.post(
            _bsky(config, "com.atproto.repo.createRecord"),
            headers={"Authorization": f"Bearer {session['accessJwt']}"},
            json={"repo": session["did"], "collection": "app.bsky.feed.post", "record": record},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise PublishError(f"Bluesky: {exc}") from exc
    if not r.ok:
        raise PublishError(f"Bluesky: {_error_message(r)}")
    uri = r.json()["uri"]
    rkey = uri.rsplit("/", 1)[-1]
    return f"https://bsky.app/profile/{session.get('handle', session['did'])}/post/{rkey}", uri


# ------------------------------------------------------------------------ entry


def check_connection(config, network):
    """Return the account name, or raise PublishError."""
    return {"mastodon": mastodon_check, "bluesky": bluesky_check}[network](config)


def message_for(config, network, article, link=""):
    template = getattr(config, f"{network}_template")
    return render_message(template, build_context(article, link), network)


def publish(config, network, article, link="", user=None):
    """Post about `article` on `network`; return the SocialPost or raise PublishError."""
    if not config.is_ready(network):
        raise PublishError(f"{network.title()} is not configured.")
    text = message_for(config, network, article, link)
    poster = {"mastodon": mastodon_post, "bluesky": bluesky_post}[network]
    url, remote_id = poster(config, text, article)
    logger.info("Published article %s on %s: %s", article.pk, network, url)
    return SocialPost.objects.create(
        article=article, network=network, url=url, remote_id=remote_id, text=text, posted_by=user
    )

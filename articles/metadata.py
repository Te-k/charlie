"""Fetch title / description / image of a web page (OpenGraph, Twitter cards, HTML)."""

import contextlib
import datetime
import email.utils
import ipaddress
import json
import logging
import re
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.conf import settings

logger = logging.getLogger(__name__)

MAX_BYTES = 2 * 1024 * 1024  # only read the first 2 MB of the page


def _is_public_host(hostname):
    """Refuse to fetch private / loopback addresses (basic SSRF protection)."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, UnicodeError):
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            return False
    return True


def _meta(soup, *keys):
    for key in keys:
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content", "").strip():
            return " ".join(tag["content"].split())
    return ""


PUBLISHED_META_KEYS = (
    "article:published_time",
    "og:article:published_time",
    "datePublished",
    "citation_publication_date",
    "citation_date",
    "DC.date.issued",
    "dcterms.issued",
    "dcterms.created",
    "parsely-pub-date",
    "sailthru.date",
    "publish-date",
    "publishdate",
    "pubdate",
    "date",
)


def parse_date(value):
    """Turn a date string found in a page into a `date`, or None.

    Accepts ISO 8601 (with or without time / timezone), YYYY/MM/DD and RFC 2822.
    The date is kept in the page's own timezone. Implausible dates are ignored.
    """
    value = (value or "").strip()
    if not value:
        return None
    parsed = None
    with contextlib.suppress(ValueError):
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    if parsed is None:
        match = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", value)
        if match:
            with contextlib.suppress(ValueError):
                parsed = datetime.date(*map(int, match.groups()))
    if parsed is None:
        with contextlib.suppress(TypeError, ValueError, IndexError):
            parsed = email.utils.parsedate_to_datetime(value).date()
    if parsed is None:
        return None
    if not datetime.date(1990, 1, 1) <= parsed <= datetime.date.today() + datetime.timedelta(1):
        return None
    return parsed


def _json_ld_dates(data):
    """Yield every datePublished value in JSON-LD data (objects, lists, @graph)."""
    if isinstance(data, list):
        for item in data:
            yield from _json_ld_dates(item)
    elif isinstance(data, dict):
        if isinstance(data.get("datePublished"), str):
            yield data["datePublished"]
        for key in ("@graph", "mainEntity", "mainEntityOfPage"):
            if key in data:
                yield from _json_ld_dates(data[key])


def _published_date(soup):
    candidates = [_meta(soup, key) for key in PUBLISHED_META_KEYS[:3]]
    for script in soup.find_all("script", type="application/ld+json"):
        with contextlib.suppress(ValueError):
            candidates.extend(_json_ld_dates(json.loads(script.string or "")))
    tag = soup.find("meta", itemprop="datePublished")
    if tag:
        candidates.append(tag.get("content", ""))
    for time in soup.find_all("time", attrs={"datetime": True}):
        if time.get("itemprop") == "datePublished" or time.has_attr("pubdate"):
            candidates.append(time["datetime"])
    candidates += [_meta(soup, key) for key in PUBLISHED_META_KEYS[3:]]
    for value in candidates:
        parsed = parse_date(value)
        if parsed:
            return parsed
    return None


def parse_metadata(html, base_url):
    soup = BeautifulSoup(html, "html.parser")

    title = _meta(soup, "og:title", "twitter:title")
    if not title and soup.title and soup.title.string:
        title = " ".join(soup.title.string.split())

    description = _meta(soup, "og:description", "twitter:description", "description")

    image = _meta(soup, "og:image:secure_url", "og:image", "twitter:image", "twitter:image:src")
    if not image:
        link = soup.find("link", rel="image_src")
        image = link.get("href", "") if link else ""
    if image:
        image = urljoin(base_url, image)
        if urlparse(image).scheme not in ("http", "https"):
            image = ""

    site_name = _meta(soup, "og:site_name", "application-name")
    published = _published_date(soup)

    return {
        "title": title,
        "description": description,
        "image_url": image,
        "site_name": site_name,
        "published_on": published.isoformat() if published else "",
    }


MAX_REDIRECTS = 5


def _get(url):
    """GET `url`, following redirects manually so every hop is checked."""
    for _ in range(MAX_REDIRECTS + 1):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return None
        if not _is_public_host(parsed.hostname):
            logger.warning("Refusing to fetch metadata from non-public host %s", parsed.hostname)
            return None
        response = requests.get(
            url,
            timeout=getattr(settings, "METADATA_FETCH_TIMEOUT", 10),
            headers={
                "User-Agent": getattr(settings, "METADATA_USER_AGENT", "CharlieBot/1.0"),
                "Accept": "text/html,application/xhtml+xml",
            },
            stream=True,
            allow_redirects=False,
        )
        if response.is_redirect and "Location" in response.headers:
            response.close()
            url = urljoin(url, response.headers["Location"])
            continue
        return response
    return None


def fetch_metadata(url):
    """Return a dict with title, description, image_url, site_name and published_on.

    Returns an empty dict on failure.
    """
    try:
        response = _get(url)
        if response is None:
            return {}
        with response:
            response.raise_for_status()
            if "html" not in response.headers.get("Content-Type", "html"):
                return {}
            content = b""
            for chunk in response.iter_content(65536):
                content += chunk
                if len(content) >= MAX_BYTES:
                    break
            # Only trust the header's charset; otherwise let BeautifulSoup
            # detect it from <meta charset> / content sniffing.
            has_charset = "charset" in response.headers.get("Content-Type", "").lower()
            encoding = response.encoding if has_charset else None
            final_url = response.url
    except requests.RequestException as exc:
        logger.info("Could not fetch metadata for %s: %s", url, exc)
        return {}

    html = content
    if encoding:
        with contextlib.suppress(LookupError):  # unknown charset name
            html = content.decode(encoding, errors="replace")
    return parse_metadata(html, final_url)


def fetch_image(url, max_bytes=1_000_000):
    """Download an image. Return (bytes, content_type), or None if it fails or is too big."""
    try:
        response = _get(url)
        if response is None:
            return None
        with response:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
            if not content_type.startswith("image/"):
                return None
            content = b""
            for chunk in response.iter_content(65536):
                content += chunk
                if len(content) > max_bytes:
                    return None
    except requests.RequestException:
        return None
    return content, content_type

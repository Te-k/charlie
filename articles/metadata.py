"""Fetch title / description / image of a web page (OpenGraph, Twitter cards, HTML)."""

import contextlib
import ipaddress
import logging
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

    return {
        "title": title,
        "description": description,
        "image_url": image,
        "site_name": site_name,
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
    """Return a dict with title, description and image_url (empty dict on failure)."""
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

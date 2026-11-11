from datetime import date
from unittest import mock

from django.test import SimpleTestCase

from articles.metadata import fetch_metadata, parse_date, parse_metadata

HTML = """
<html><head>
  <title>  Fallback   title </title>
  <meta property="og:title" content="OG Title">
  <meta name="description" content="Plain description">
  <meta property="og:image" content="/img/cover.jpg">
</head><body></body></html>
"""


class ParseMetadataTests(SimpleTestCase):
    def test_prefers_opengraph(self):
        meta = parse_metadata(HTML, "https://example.com/post/1")
        self.assertEqual(meta["title"], "OG Title")
        self.assertEqual(meta["description"], "Plain description")
        self.assertEqual(meta["image_url"], "https://example.com/img/cover.jpg")

    def test_falls_back_to_title_tag(self):
        meta = parse_metadata("<title> Hello\n world </title>", "https://example.com/")
        self.assertEqual(
            meta,
            {
                "title": "Hello world",
                "description": "",
                "image_url": "",
                "site_name": "",
                "published_on": "",
            },
        )

    def test_rejects_non_http_images(self):
        html = '<meta property="og:image" content="javascript:alert(1)">'
        self.assertEqual(parse_metadata(html, "https://example.com/")["image_url"], "")


class FetchMetadataTests(SimpleTestCase):
    def test_refuses_private_hosts(self):
        with mock.patch("articles.metadata.requests.get") as get:
            self.assertEqual(fetch_metadata("http://127.0.0.1/"), {})
            self.assertEqual(fetch_metadata("http://localhost:8000/admin/"), {})
            get.assert_not_called()

    def test_refuses_non_http(self):
        self.assertEqual(fetch_metadata("file:///etc/passwd"), {})


class PublishedDateTests(SimpleTestCase):
    def date_of(self, head="", body=""):
        html = f"<html><head>{head}</head><body>{body}</body></html>"
        return parse_metadata(html, "https://example.com/")["published_on"]

    def test_parse_date_formats(self):
        for value, expected in (
            ("2026-11-02T08:30:00+01:00", date(2026, 11, 2)),
            ("2026-11-02T23:30:00Z", date(2026, 11, 2)),  # kept in the page's timezone
            ("2026-11-02", date(2026, 11, 2)),
            ("2026/11/02 10:00", date(2026, 11, 2)),
            ("Mon, 02 Nov 2026 10:00:00 GMT", date(2026, 11, 2)),
            ("1850-01-01", None),  # implausible
            ("2999-01-01", None),
            ("yesterday", None),
            ("", None),
        ):
            self.assertEqual(parse_date(value), expected, value)

    def test_opengraph_article_time(self):
        head = '<meta property="article:published_time" content="2026-11-02T08:30:00+01:00">'
        self.assertEqual(self.date_of(head), "2026-11-02")

    def test_json_ld_graph(self):
        head = """<script type="application/ld+json">
          {"@context": "https://schema.org", "@graph": [
            {"@type": "WebPage"},
            {"@type": "NewsArticle", "datePublished": "2026-10-30T12:00:00Z"}
          ]}</script>"""
        self.assertEqual(self.date_of(head), "2026-10-30")

    def test_broken_json_ld_is_ignored(self):
        head = (
            '<script type="application/ld+json">{oops</script>'
            '<meta name="date" content="2026-01-05">'
        )
        self.assertEqual(self.date_of(head), "2026-01-05")

    def test_time_element(self):
        body = '<time itemprop="datePublished" datetime="2026-09-01">Sept 1</time>'
        self.assertEqual(self.date_of(body=body), "2026-09-01")

    def test_specific_tags_win_over_generic_date(self):
        head = (
            '<meta name="date" content="2026-01-05">'
            '<meta property="article:published_time" content="2026-01-01">'
        )
        self.assertEqual(self.date_of(head), "2026-01-01")

    def test_no_date(self):
        self.assertEqual(self.date_of("<title>x</title>"), "")

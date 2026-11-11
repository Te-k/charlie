from unittest import mock

from django.test import SimpleTestCase

from articles.metadata import fetch_metadata, parse_metadata

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
            {"title": "Hello world", "description": "", "image_url": "", "site_name": ""},
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

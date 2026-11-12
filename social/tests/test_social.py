import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from articles.models import Article, SiteSettings, Tag
from social import publishers
from social.models import SocialPost, SocialSettings


def fake_response(status=200, payload=None):
    r = mock.Mock()
    r.ok = 200 <= status < 300
    r.status_code = status
    r.json.return_value = payload or {}
    return r


class MessageTests(SimpleTestCase):
    def test_hashtag(self):
        self.assertEqual(publishers.hashtag("Machine learning"), "#MachineLearning")
        self.assertEqual(publishers.hashtag("Security & Privacy"), "#SecurityPrivacy")
        self.assertEqual(publishers.hashtag("rust"), "#rust")
        self.assertEqual(publishers.hashtag("!!"), "")

    def test_fill_drops_empty_lines_and_keeps_unknown_placeholders(self):
        text = publishers.fill(
            "{title}\n\n{description}\n\n{url} {nope}",
            {
                "title": "T",
                "description": "",
                "url": "https://x.y",
            },
        )
        self.assertEqual(text, "T\n\nhttps://x.y {nope}")

    def test_no_attribute_access_in_templates(self):
        self.assertEqual(publishers.fill("{title.__class__}", {"title": "T"}), "{title.__class__}")

    def test_long_description_is_shortened_to_fit(self):
        context = {
            "title": "Title",
            "description": "word " * 200,
            "url": "https://example.com/" + "a" * 100,
        }
        text = publishers.render_message("{title}\n\n{description}\n\n{url}", context, "bluesky")
        self.assertLessEqual(len(text), 300)
        self.assertTrue(text.startswith("Title\n\nword"))
        self.assertTrue(text.endswith(context["url"]))
        self.assertIn("…", text)

    def test_mastodon_counts_links_as_23_characters(self):
        url = "https://example.com/" + "a" * 600
        self.assertEqual(publishers.text_length(f"hi {url}", "mastodon"), 3 + 23)
        context = {"title": "T", "description": "", "url": url}
        self.assertEqual(
            publishers.render_message("{title} {url}", context, "mastodon"), f"T {url}"
        )

    def test_bluesky_facets_use_byte_offsets(self):
        text = "Café ☕ https://example.com/a. #Rust"
        facets = publishers.bluesky_facets(text)
        link, tag = facets
        encoded = text.encode()
        span = link["index"]
        self.assertEqual(encoded[span["byteStart"] : span["byteEnd"]], b"https://example.com/a")
        self.assertEqual(link["features"][0]["uri"], "https://example.com/a")
        span = tag["index"]
        self.assertEqual(encoded[span["byteStart"] : span["byteEnd"]], b"#Rust")
        self.assertEqual(tag["features"][0]["tag"], "Rust")

    def test_hash_in_url_is_not_a_hashtag(self):
        facets = publishers.bluesky_facets("https://example.com/#section")
        self.assertEqual(len(facets), 1)


class SocialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.staff = User.objects.create_user("admin", password="pw", is_staff=True)
        cls.user = User.objects.create_user("bob", password="pw")
        cls.article = Article.objects.create(
            url="https://example.com/story",
            title="A story",
            description="About things",
            image_url="https://example.com/pic.jpg",
        )
        cls.article.tags.add(Tag.objects.create(name="Open Source"))

    def configure(self, **extra):
        config = SocialSettings.load()
        values = dict(
            mastodon_enabled=True,
            mastodon_instance="https://mastodon.example",
            mastodon_access_token="tok",
            bluesky_enabled=True,
            bluesky_handle="alice.bsky.social",
            bluesky_app_password="app-pw",
        )
        values.update(extra)
        for key, value in values.items():
            setattr(config, key, value)
        config.save()
        return config

    # ------------------------------------------------------------- settings page

    def test_settings_page_is_staff_only(self):
        url = reverse("social:settings")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.staff)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A story")  # preview uses the latest article

    def test_settings_keep_secrets_when_left_empty(self):
        self.configure()
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("social:settings"),
            {
                "site-site_name": "Charlie",
                "site-languages": ["en"],
                "site-default_language": "en",
                "mastodon_enabled": "on",
                "mastodon_instance": "https://mastodon.example",
                "mastodon_access_token": "",
                "mastodon_visibility": "unlisted",
                "mastodon_template": "{title} {url}",
                "bluesky_service": "https://bsky.social",
                "bluesky_handle": "alice.bsky.social",
                "bluesky_app_password": "",
                "bluesky_template": "{title}",
            },
        )
        self.assertRedirects(response, reverse("social:settings"))
        config = SocialSettings.load()
        self.assertEqual(config.mastodon_access_token, "tok")
        self.assertEqual(config.bluesky_app_password, "app-pw")
        self.assertEqual(config.mastodon_template, "{title} {url}")
        self.assertEqual(config.mastodon_visibility, "unlisted")
        self.assertFalse(config.bluesky_enabled)
        # Secrets are never sent back to the browser.
        self.assertNotContains(self.client.get(reverse("social:settings")), "app-pw")

    def test_change_site_name(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("social:settings"),
            {
                "site-site_name": "My Reading List",
                "site-languages": ["en"],
                "site-default_language": "en",
                "mastodon_template": "{title}",
                "bluesky_template": "{title}",
                "mastodon_visibility": "public",
                "bluesky_service": "https://bsky.social",
            },
        )
        self.assertRedirects(response, reverse("social:settings"))
        home = self.client.get(reverse("articles:home"))
        self.assertContains(home, "My Reading List<span")
        self.assertContains(home, "<title>Latest articles · My Reading List</title>", html=False)
        self.assertNotContains(home, "Charlie")
        self.assertContains(
            self.client.get(reverse("articles:feed")),
            "<title>My Reading List – latest articles</title>",
        )
        self.assertContains(
            self.client.get(reverse("articles:tag_feed", args=["open-source"])),
            "<title>My Reading List – tag: Open Source</title>",
        )

    def test_site_name_is_required(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("social:settings"),
            {
                "site-site_name": "  ",
                "site-languages": ["en"],
                "site-default_language": "en",
                "mastodon_template": "{title}",
                "bluesky_template": "{title}",
                "mastodon_visibility": "public",
                "bluesky_service": "https://bsky.social",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["site_form"], "site_name", "This field is required.")
        self.assertEqual(SiteSettings.load().site_name, "Charlie")

    def test_enabling_requires_credentials(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("social:settings"),
            {
                "site-site_name": "Charlie",
                "site-languages": ["en"],
                "site-default_language": "en",
                "bluesky_enabled": "on",
                "bluesky_service": "https://bsky.social",
                "mastodon_template": "x",
                "bluesky_template": "x",
                "mastodon_visibility": "public",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"], "bluesky_handle", "Required to enable posting."
        )

    @mock.patch("social.publishers.requests.get")
    def test_test_connection(self, get):
        self.configure()
        get.return_value = fake_response(payload={"acct": "alice"})
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("social:settings"),
            {
                "site-site_name": "Charlie",
                "site-languages": ["en"],
                "site-default_language": "en",
                "action": "test_mastodon",
                "mastodon_enabled": "on",
                "mastodon_instance": "https://mastodon.example",
                "mastodon_visibility": "public",
                "mastodon_template": "{title}",
                "bluesky_service": "https://bsky.social",
                "bluesky_template": "{title}",
            },
            follow=True,
        )
        self.assertContains(response, "connected as @alice")
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer tok")

    # ---------------------------------------------------------------- posting

    @mock.patch("social.publishers.requests.post")
    def test_publish_on_mastodon(self, post):
        config = self.configure(
            mastodon_template="{title}\n{url}\n{tags}", mastodon_visibility="unlisted"
        )
        post.return_value = fake_response(
            payload={"id": "42", "url": "https://mastodon.example/@me/42"}
        )
        social_post = publishers.publish(config, "mastodon", self.article)
        self.assertEqual(social_post.url, "https://mastodon.example/@me/42")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://mastodon.example/api/v1/statuses")
        self.assertEqual(
            kwargs["data"],
            {
                "status": "A story\nhttps://example.com/story\n#OpenSource",
                "visibility": "unlisted",
            },
        )

    @mock.patch("social.publishers.fetch_image", return_value=(b"img", "image/jpeg"))
    @mock.patch("social.publishers.requests.post")
    def test_publish_on_bluesky_with_link_card(self, post, fetch_image):
        config = self.configure(bluesky_template="{title} {tags}")
        post.side_effect = [
            fake_response(
                payload={"accessJwt": "jwt", "did": "did:plc:abc", "handle": "alice.bsky.social"}
            ),
            fake_response(payload={"blob": {"ref": "blobref"}}),
            fake_response(payload={"uri": "at://did:plc:abc/app.bsky.feed.post/3kxyz", "cid": "c"}),
        ]
        social_post = publishers.publish(config, "bluesky", self.article)
        self.assertEqual(social_post.url, "https://bsky.app/profile/alice.bsky.social/post/3kxyz")
        session_call, blob_call, record_call = post.call_args_list
        self.assertEqual(
            session_call.kwargs["json"], {"identifier": "alice.bsky.social", "password": "app-pw"}
        )
        self.assertEqual(blob_call.kwargs["data"], b"img")
        record = record_call.kwargs["json"]["record"]
        self.assertEqual(record["text"], "A story #OpenSource")
        self.assertEqual(record["facets"][0]["features"][0]["tag"], "OpenSource")
        external = record["embed"]["external"]
        self.assertEqual(external["uri"], "https://example.com/story")
        self.assertEqual(external["thumb"], {"ref": "blobref"})
        json.dumps(record)  # serialisable

    @mock.patch("social.publishers.requests.post")
    def test_publish_error_is_reported(self, post):
        config = self.configure()
        post.return_value = fake_response(401, {"error": "The access token is invalid"})
        with self.assertRaisesMessage(publishers.PublishError, "The access token is invalid"):
            publishers.publish(config, "mastodon", self.article)
        self.assertFalse(SocialPost.objects.exists())

    # ------------------------------------------------- integration with articles

    @mock.patch("articles.metadata.fetch_metadata", return_value={"title": "Fetched"})
    @mock.patch("social.publishers.mastodon_post", return_value=("https://m.example/1", "1"))
    @mock.patch("social.publishers.bluesky_post", return_value=("https://bsky.app/x", "at://x"))
    def test_add_article_and_publish(self, bluesky_post, mastodon_post, fetch):
        self.configure(bluesky_default=False)
        self.client.force_login(self.user)
        add_url = reverse("articles:article_add")

        response = self.client.post(add_url, {"action": "fetch", "url": "https://example.com/new"})
        form = response.context["form"]
        self.assertTrue(form["post_mastodon"].value())  # checked by default
        self.assertFalse(form["post_bluesky"].value())  # unchecked by default

        response = self.client.post(
            add_url,
            {
                "action": "save",
                "url": "https://example.com/new",
                "title": "Fetched",
                "post_mastodon": "on",
            },
            follow=True,
        )
        article = Article.objects.get(url="https://example.com/new")
        mastodon_post.assert_called_once()
        bluesky_post.assert_not_called()
        self.assertEqual(article.social_posts.get().url, "https://m.example/1")
        self.assertContains(response, "Posted on Mastodon")

    @mock.patch(
        "social.publishers.mastodon_post", side_effect=publishers.PublishError("Mastodon: boom")
    )
    def test_failed_post_keeps_article_and_allows_retry(self, mastodon_post):
        self.configure(bluesky_enabled=False)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("articles:article_add"),
            {
                "action": "save",
                "url": "https://example.com/new2",
                "title": "T",
                "post_mastodon": "on",
            },
            follow=True,
        )
        self.assertTrue(Article.objects.filter(url="https://example.com/new2").exists())
        self.assertContains(response, "Could not post on Mastodon")
        self.assertContains(response, "Post on Mastodon")  # retry button on the article page

    def test_no_publish_fields_when_not_configured(self):
        self.client.force_login(self.user)
        with mock.patch("articles.metadata.fetch_metadata", return_value={}):
            response = self.client.post(
                reverse("articles:article_add"), {"action": "fetch", "url": "https://example.com/z"}
            )
        self.assertNotIn("post_mastodon", response.context["form"].fields)
        self.assertNotContains(response, "Share when saving")

    @mock.patch("social.publishers.mastodon_post", return_value=("https://m.example/2", "2"))
    def test_share_button(self, mastodon_post):
        self.configure()
        url = reverse("social:share", args=[self.article.pk, "mastodon"])
        self.assertEqual(self.client.post(url).status_code, 302)
        mastodon_post.assert_not_called()  # anonymous
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url, follow=True)
        self.assertContains(response, "https://m.example/2")
        self.assertContains(response, "Post again on Mastodon")

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from articles.models import Article, Country, Organization, Tag

META = {
    "title": "Fetched title",
    "description": "Fetched desc",
    "image_url": "https://example.com/a.png",
    "published_on": "2026-11-02",
}


@override_settings(ARTICLES_PER_PAGE=20)
class ViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("alice", password="pw")
        cls.tag = Tag.objects.create(name="Machine Learning")
        cls.organization = Organization.objects.create(name="ACME Corp")
        cls.france = Country.objects.get(code="FR")

    def make_articles(self, n):
        return [
            Article.objects.create(url=f"https://example.com/{i}", title=f"Article {i}")
            for i in range(n)
        ]

    def test_home_newest_first_and_paginated(self):
        self.make_articles(25)
        response = self.client.get(reverse("articles:home"))
        titles = [a.title for a in response.context["articles"]]
        self.assertEqual(len(titles), 20)
        self.assertEqual(titles[0], "Article 24")
        response = self.client.get(reverse("articles:home") + "?page=2")
        self.assertEqual([a.title for a in response.context["articles"]][-1], "Article 0")

    def test_filtered_pages(self):
        a, b = self.make_articles(2)
        a.tags.add(self.tag)
        a.organizations.add(self.organization)
        b.countries.add(self.france)
        for url, expected in [
            (reverse("articles:tag", args=["machine-learning"]), [a]),
            (reverse("articles:organization", args=["acme-corp"]), [a]),
            (reverse("articles:country", args=["fr"]), [b]),
        ]:
            response = self.client.get(url)
            self.assertEqual(list(response.context["articles"]), expected, url)
        self.assertEqual(self.client.get(reverse("articles:tag", args=["nope"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("articles:country", args=["zz"])).status_code, 404)

    def test_index_pages(self):
        a = self.make_articles(1)[0]
        a.countries.add(self.france)
        for name in ("tags", "organizations", "countries"):
            self.assertEqual(self.client.get(reverse(f"articles:{name}")).status_code, 200)
        countries = self.client.get(reverse("articles:countries")).context["items"]
        self.assertEqual(len(countries), Country.objects.count())
        self.assertGreater(len(countries), 200)
        self.assertEqual(next(c for c in countries if c == self.france).article_count, 1)

    def test_adding_requires_login(self):
        for name in ("article_add", "tag_add", "organization_add"):
            response = self.client.get(reverse(f"articles:{name}"))
            self.assertRedirects(response, f"{reverse('login')}?next={reverse(f'articles:{name}')}")
        response = self.client.post(
            reverse("articles:article_add"), {"url": "https://example.com/x"}
        )
        self.assertEqual(Article.objects.count(), 0)

    def test_no_registration(self):
        self.assertEqual(self.client.get("/register/").status_code, 404)
        self.assertEqual(self.client.get("/accounts/signup/").status_code, 404)

    @mock.patch("articles.metadata.fetch_metadata", return_value=META)
    def test_add_article_fetch_then_review_then_save(self, fetch):
        self.client.force_login(self.user)
        add_url = reverse("articles:article_add")

        # Step 1: only the URL.
        response = self.client.get(add_url)
        self.assertTemplateUsed(response, "articles/article_add_url.html")

        # Fetching shows the pre-filled form but saves nothing.
        response = self.client.post(add_url, {"action": "fetch", "url": "https://example.com/post"})
        fetch.assert_called_once_with("https://example.com/post")
        self.assertTemplateUsed(response, "articles/article_form.html")
        self.assertFalse(Article.objects.exists())
        self.assertContains(response, 'value="Fetched title"')
        self.assertContains(response, "Fetched desc")
        self.assertContains(response, 'src="https://example.com/a.png"')
        self.assertContains(response, 'value="2026-11-02"')

        # The user corrects the title and saves.
        response = self.client.post(
            add_url,
            {
                "action": "save",
                "url": "https://example.com/post",
                "title": "Corrected title",
                "description": "Fetched desc",
                "image_url": "https://example.com/a.png",
                "published_on": "2026-11-01",
                "tags": [self.tag.pk],
                "countries": [self.france.pk],
            },
        )
        article = Article.objects.get()
        self.assertRedirects(response, article.get_absolute_url())
        self.assertEqual(fetch.call_count, 1)  # no fetch on save
        self.assertEqual(article.title, "Corrected title")
        self.assertEqual(article.image_url, "https://example.com/a.png")
        self.assertEqual(str(article.published_on), "2026-11-01")  # corrected by the user
        self.assertContains(
            self.client.get(article.get_absolute_url()), "Published November 1, 2026"
        )
        self.assertContains(self.client.get(reverse("articles:home")), "Nov 1, 2026")
        self.assertEqual(article.added_by, self.user)
        self.assertEqual(list(article.tags.all()), [self.tag])
        self.assertEqual(list(article.countries.all()), [self.france])

    @mock.patch("articles.metadata.fetch_metadata", return_value=META)
    def test_add_article_from_query_string(self, fetch):
        self.client.force_login(self.user)
        response = self.client.get(reverse("articles:article_add") + "?url=https://example.com/q")
        self.assertContains(response, 'value="Fetched title"')
        self.assertFalse(Article.objects.exists())

    @mock.patch("articles.metadata.fetch_metadata", return_value={})
    def test_add_article_fetch_failure_still_allows_manual_entry(self, fetch):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("articles:article_add"), {"action": "fetch", "url": "https://example.com/x"}
        )
        self.assertTemplateUsed(response, "articles/article_form.html")
        self.assertContains(response, "Could not fetch details")

    @mock.patch("articles.metadata.fetch_metadata", return_value=META)
    def test_add_existing_url_is_refused(self, fetch):
        existing = self.make_articles(1)[0]
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("articles:article_add"), {"action": "fetch", "url": existing.url}
        )
        self.assertTemplateUsed(response, "articles/article_add_url.html")
        self.assertContains(response, existing.get_absolute_url())
        fetch.assert_not_called()

    @mock.patch("articles.metadata.fetch_metadata", return_value=META)
    def test_edit_fetch_again_does_not_save(self, fetch):
        article = self.make_articles(1)[0]
        article.tags.add(self.tag)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("articles:article_edit", args=[article.pk]),
            {
                "action": "fetch",
                "url": article.url,
                "title": "Old",
                "tags": [self.tag.pk],
            },
        )
        self.assertContains(response, 'value="Fetched title"')
        article.refresh_from_db()
        self.assertEqual(article.title, "Article 0")
        # Selected tags are kept in the review form.
        self.assertEqual(response.context["form"]["tags"].value(), [str(self.tag.pk)])

    def test_add_tag_and_organization(self):
        self.client.force_login(self.user)
        self.client.post(reverse("articles:tag_add"), {"name": "Security & Privacy"})
        self.assertTrue(Tag.objects.filter(slug="security-privacy").exists())
        self.client.post(reverse("articles:organization_add"), {"name": "Initech", "website": ""})
        self.assertTrue(Organization.objects.filter(slug="initech").exists())

    def test_edit_and_delete(self):
        article = self.make_articles(1)[0]
        edit_url = reverse("articles:article_edit", args=[article.pk])
        delete_url = reverse("articles:article_delete", args=[article.pk])
        # Anonymous visitors see no links and are sent to the login page.
        self.assertNotContains(self.client.get(reverse("articles:home")), edit_url)
        self.assertRedirects(self.client.get(edit_url), f"{reverse('login')}?next={edit_url}")
        self.client.post(delete_url)
        self.assertTrue(Article.objects.exists())

        self.client.force_login(self.user)
        home = self.client.get(reverse("articles:home"))
        self.assertContains(home, edit_url)
        self.assertContains(home, delete_url)
        self.assertEqual(self.client.get(delete_url).status_code, 200)  # confirmation page
        self.client.post(
            reverse("articles:article_edit", args=[article.pk]),
            {"url": article.url, "title": "New"},
        )
        article.refresh_from_db()
        self.assertEqual(article.title, "New")
        self.client.post(reverse("articles:article_delete", args=[article.pk]))
        self.assertFalse(Article.objects.exists())

    def test_rss_feeds(self):
        a = self.make_articles(1)[0]
        a.image_url = "https://example.com/pic.png"
        a.save()
        a.tags.add(self.tag)
        response = self.client.get(reverse("articles:feed"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/rss+xml", response["Content-Type"])
        body = response.content.decode()
        self.assertIn("<title>Article 0</title>", body)
        self.assertIn("https://example.com/0", body)
        self.assertIn('type="image/png"', body)
        self.assertIn("<category>Machine Learning</category>", body)
        for url in (
            reverse("articles:tag_feed", args=["machine-learning"]),
            reverse("articles:organization_feed", args=["acme-corp"]),
            reverse("articles:country_feed", args=["fr"]),
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_old_company_urls_redirect(self):
        for old, new in (
            ("/companies/", reverse("articles:organizations")),
            ("/companies/acme-corp/", reverse("articles:organization", args=["acme-corp"])),
            (
                "/companies/acme-corp/feed/",
                reverse("articles:organization_feed", args=["acme-corp"]),
            ),
            ("/companies/acme-corp/?page=2", "/organizations/acme-corp/?page=2"),
        ):
            response = self.client.get(old)
            self.assertRedirects(response, new, status_code=301, fetch_redirect_response=False)

    @mock.patch("articles.metadata.fetch_metadata", return_value=META)
    def test_added_date_can_be_set_when_adding(self, fetch):
        self.client.force_login(self.user)
        add_url = reverse("articles:article_add")
        response = self.client.post(add_url, {"action": "fetch", "url": "https://example.com/d"})
        self.assertContains(response, 'type="datetime-local"')
        self.assertTrue(response.context["form"]["created_at"].value())  # pre-filled with now

        save = {"action": "save", "url": "https://example.com/d", "title": "D"}
        response = self.client.post(add_url, {**save, "created_at": "2099-01-01T10:00"})
        self.assertContains(response, "can&#x27;t be in the future")
        self.assertFalse(Article.objects.exists())

        self.client.post(add_url, {**save, "created_at": "2025-03-04T10:30"})
        article = Article.objects.get()
        self.assertEqual(article.created_at.isoformat(), "2025-03-04T10:30:00+00:00")

        # Not offered on the edit form.
        response = self.client.get(reverse("articles:article_edit", args=[article.pk]))
        self.assertNotContains(response, 'type="datetime-local"')

    def test_added_date_defaults_to_now(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("articles:article_add"),
            {"action": "save", "url": "https://example.com/e", "title": "E", "created_at": ""},
        )
        article = Article.objects.get()
        self.assertLess((timezone.now() - article.created_at).total_seconds(), 60)

    def test_detail_page_archive_links(self):
        article = Article.objects.create(url="https://example.com/a?b=1", title="A")
        response = self.client.get(article.get_absolute_url())
        self.assertContains(
            response, 'href="https://web.archive.org/web/https://example.com/a?b=1"'
        )
        self.assertContains(response, 'href="https://archive.li/https://example.com/a?b=1"')

    def test_who_added_an_article_is_never_shown(self):
        article = Article.objects.create(url="https://example.com/a", added_by=self.user)
        for url in (
            reverse("articles:home"),
            article.get_absolute_url(),
            reverse("articles:feed"),
        ):
            self.assertNotContains(self.client.get(url), "alice", msg_prefix=url)

    def test_login_page(self):
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)
        response = self.client.post(reverse("login"), {"username": "alice", "password": "pw"})
        self.assertRedirects(response, reverse("articles:home"))
        self.assertContains(self.client.get(reverse("articles:home")), "+ Article")

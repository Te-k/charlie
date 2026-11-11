from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from articles.forms import PublisherForm
from articles.models import Article, Publisher, url_domain


class PublisherMatchingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lemonde = Publisher.objects.create(
            name="Le Monde",
            website="https://www.lemonde.fr/",
            alternative_website="https://lemonde.io",
        )

    def test_url_domain(self):
        self.assertEqual(url_domain("https://WWW.LeMonde.fr/a?b"), "lemonde.fr")
        self.assertEqual(url_domain("not a url"), "")
        self.assertEqual(url_domain(""), "")

    def test_matches_website_alternative_and_subdomains(self):
        for url in (
            "https://www.lemonde.fr/x",
            "http://lemonde.fr/x",
            "https://lemonde.io/y",
            "https://blog.lemonde.fr/z",
        ):
            self.assertEqual(Publisher.objects.for_url(url), self.lemonde, url)
        self.assertIsNone(Publisher.objects.for_url("https://lemonde.com/"))
        self.assertIsNone(Publisher.objects.for_url("https://notlemonde.fr/"))

    def test_most_specific_domain_wins(self):
        blog = Publisher.objects.create(name="Le Monde blogs", website="https://blog.lemonde.fr")
        self.assertEqual(Publisher.objects.for_url("https://blog.lemonde.fr/a"), blog)
        self.assertEqual(Publisher.objects.for_url("https://www.lemonde.fr/a"), self.lemonde)

    def test_article_save_links_existing_publisher(self):
        article = Article.objects.create(url="https://www.lemonde.fr/article")
        self.assertEqual(article.publisher, self.lemonde)

    def test_article_save_creates_missing_publisher(self):
        article = Article.objects.create(url="https://www.example.com/post")
        publisher = article.publisher
        self.assertEqual(publisher.name, "example.com")
        self.assertEqual(publisher.website, "https://www.example.com/")
        self.assertEqual(publisher.domain, "example.com")
        # The next article on the same site reuses it.
        other = Article.objects.create(url="https://example.com/other")
        self.assertEqual(other.publisher, publisher)
        self.assertEqual(Publisher.objects.count(), 2)

    def test_new_publisher_uses_hint_and_avoids_name_clash(self):
        article = Article(url="https://lemonde.ca/x")
        article.publisher_name = "Le Monde"
        article.save()
        self.assertEqual(article.publisher.name, "Le Monde (lemonde.ca)")

    def test_explicit_publisher_is_kept(self):
        article = Article.objects.create(url="https://example.com/x", publisher=self.lemonde)
        self.assertEqual(article.publisher, self.lemonde)

    def test_form_refuses_domain_of_another_publisher(self):
        form = PublisherForm(
            {"name": "Copy", "website": "https://lemonde.io/", "alternative_website": ""}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Le Monde", form.errors["website"][0])
        form = PublisherForm(
            {
                "name": "Same",
                "website": "https://a.example",
                "alternative_website": "https://www.a.example",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("alternative_website", form.errors)
        # Editing a publisher doesn't clash with itself.
        form = PublisherForm(
            {"name": "Le Monde", "website": "https://lemonde.fr", "alternative_website": ""},
            instance=self.lemonde,
        )
        self.assertTrue(form.is_valid(), form.errors)


class PublisherViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("bob", password="pw")
        cls.lemonde = Publisher.objects.create(
            name="Le Monde", website="https://www.lemonde.fr/", description="French daily."
        )

    def test_pages_and_links(self):
        article = Article.objects.create(url="https://www.lemonde.fr/a", title="Un article")
        Article.objects.create(url="https://example.com/b", title="Elsewhere")
        page = reverse("articles:publisher", args=["le-monde"])
        response = self.client.get(page)
        self.assertEqual([a.title for a in response.context["articles"]], ["Un article"])
        self.assertContains(response, "French daily.")
        self.assertContains(self.client.get(reverse("articles:publishers")), "Le Monde")
        self.assertContains(self.client.get(reverse("articles:home")), f'href="{page}"')
        self.assertContains(self.client.get(article.get_absolute_url()), f'href="{page}"')
        feed = self.client.get(reverse("articles:publisher_feed", args=["le-monde"]))
        self.assertContains(feed, "Un article")
        self.assertNotContains(feed, "Elsewhere")

    @mock.patch(
        "articles.metadata.fetch_metadata",
        return_value={"title": "T", "description": "", "image_url": "", "site_name": "Example"},
    )
    def test_add_flow_detects_or_announces_publisher(self, fetch):
        self.client.force_login(self.user)
        add_url = reverse("articles:article_add")

        response = self.client.post(add_url, {"action": "fetch", "url": "https://lemonde.fr/x"})
        self.assertEqual(response.context["form"]["publisher"].value(), str(self.lemonde.pk))
        self.assertNotIn("new_publisher", response.context)

        response = self.client.post(add_url, {"action": "fetch", "url": "https://example.com/y"})
        self.assertEqual(response.context["new_publisher"], "Example")
        self.assertContains(response, "Saving creates <strong")
        self.assertContains(response, 'name="publisher_name" value="Example"')
        self.assertFalse(Publisher.objects.filter(domain="example.com").exists())  # not yet

        self.client.post(
            add_url,
            {
                "action": "save",
                "url": "https://example.com/y",
                "title": "T",
                "publisher": "",
                "publisher_name": "Example",
            },
        )
        self.assertEqual(Article.objects.get().publisher.name, "Example")

    def test_changing_url_on_edit_finds_publisher_again(self):
        article = Article.objects.create(url="https://example.com/a", title="A")
        self.client.force_login(self.user)
        self.client.post(
            reverse("articles:article_edit", args=[article.pk]),
            {
                "action": "save",
                "url": "https://www.lemonde.fr/a",
                "title": "A",
                "publisher": article.publisher.pk,
            },
        )
        article.refresh_from_db()
        self.assertEqual(article.publisher, self.lemonde)

    def test_add_and_edit_publisher(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("articles:publisher_add"),
            {"name": "The Paper", "website": "https://paper.example", "description": ""},
        )
        paper = Publisher.objects.get(name="The Paper")
        self.assertEqual(paper.domain, "paper.example")
        response = self.client.post(
            reverse("articles:publisher_edit", args=[paper.slug]),
            {
                "name": "The Paper",
                "website": "https://paper.example",
                "alternative_website": "https://thepaper.example",
                "description": "Daily news.",
            },
        )
        self.assertRedirects(response, paper.get_absolute_url())
        paper.refresh_from_db()
        self.assertEqual(paper.alternative_domain, "thepaper.example")
        self.assertEqual(Publisher.objects.for_url("https://thepaper.example/x"), paper)

    def test_editing_requires_login(self):
        response = self.client.get(reverse("articles:publisher_edit", args=["le-monde"]))
        self.assertEqual(response.status_code, 302)

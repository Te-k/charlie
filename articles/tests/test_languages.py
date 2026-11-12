from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from articles.forms import ArticleForm, SiteSettingsForm
from articles.models import Article, SiteSettings

META = {"title": "T", "description": "", "image_url": ""}


class LanguageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_user("staff", password="pw", is_staff=True)

    def set_languages(self, languages, default="en"):
        site = SiteSettings.load()
        site.languages, site.default_language = languages, default
        site.save()

    def test_new_articles_default_to_english(self):
        self.assertEqual(Article.objects.create(url="https://example.com/a").language, "en")
        self.assertEqual(SiteSettings.load().language_choices(), [("en", "English")])

    def test_form_offers_configured_languages(self):
        self.set_languages(["fr", "en", "de"], default="fr")
        form = ArticleForm()
        self.assertEqual(
            list(form.fields["language"].choices),
            [("en", "English"), ("fr", "French"), ("de", "German")],
        )
        self.assertEqual(form.fields["language"].initial, "fr")
        # A language that isn't offered is refused; an empty one means the default.
        data = {"url": "https://example.com/x", "language": "it"}
        self.assertIn("language", ArticleForm(data).errors)
        form = ArticleForm({"url": "https://example.com/x", "language": ""})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["language"], "fr")

    def test_removed_language_stays_selectable_on_edit(self):
        article = Article.objects.create(url="https://example.com/a", language="it")
        form = ArticleForm(instance=article)
        self.assertIn(("it", "Italian"), list(form.fields["language"].choices))
        self.assertEqual(form.fields["language"].initial, "it")

    @mock.patch("articles.metadata.fetch_metadata", return_value=META)
    def test_add_flow_preselects_default_and_saves_choice(self, fetch):
        self.set_languages(["en", "fr"])
        self.client.force_login(self.staff)
        add_url = reverse("articles:article_add")
        response = self.client.post(add_url, {"action": "fetch", "url": "https://example.com/f"})
        self.assertEqual(response.context["form"]["language"].value(), "en")
        self.client.post(
            add_url,
            {"action": "save", "url": "https://example.com/f", "title": "F", "language": "fr"},
        )
        self.assertEqual(Article.objects.get().language, "fr")

    def test_language_shown_on_pages(self):
        article = Article.objects.create(url="https://example.com/a", title="Un", language="fr")
        Article.objects.create(url="https://example.com/b", title="Two")
        detail = self.client.get(article.get_absolute_url())
        self.assertContains(detail, "French")
        self.assertContains(detail, 'lang="fr"')
        home = self.client.get(reverse("articles:home"))
        # Only articles not in the default language get a label in lists.
        self.assertContains(home, 'title="French"')
        self.assertNotContains(home, 'title="English"')

    def test_settings_form(self):
        data = {"site_name": "X", "languages": ["en", "fr"], "default_language": "de"}
        form = SiteSettingsForm(data)
        self.assertIn("default_language", form.errors)
        form = SiteSettingsForm({**data, "default_language": "fr"})
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        site = SiteSettings.load()
        self.assertEqual((site.languages, site.default_language), (["en", "fr"], "fr"))

    def test_settings_page_shows_languages(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("social:settings"))
        self.assertContains(response, "Article languages")

from django import forms
from django.db.models import Q
from django.utils import timezone

from .models import (
    ALL_LANGUAGES,
    Article,
    Organization,
    Publisher,
    SiteSettings,
    Tag,
    language_name,
    url_domain,
)


class ArticleUrlForm(forms.Form):
    """First step of adding an article: just the URL."""

    url = forms.URLField(
        label="URL",
        max_length=2000,
        assume_scheme="https",
        widget=forms.URLInput(attrs={"placeholder": "https://…", "autofocus": True}),
    )

    def clean_url(self):
        url = self.cleaned_data["url"]
        existing = Article.objects.filter(url=url).first()
        if existing:
            self.existing_article = existing
            raise forms.ValidationError("This article has already been added.")
        return url


class ArticleForm(forms.ModelForm):
    # Name for a new publisher (the page's og:site_name), filled in by the fetch step.
    publisher_name = forms.CharField(required=False, max_length=100, widget=forms.HiddenInput)

    class Meta:
        model = Article
        fields = [
            "url",
            "title",
            "description",
            "image_url",
            "published_on",
            "language",
            "publisher",
            "tags",
            "countries",
            "organizations",
        ]
        labels = {"url": "URL", "image_url": "Photo URL"}
        widgets = {
            "url": forms.URLInput(attrs={"placeholder": "https://…"}),
            "description": forms.Textarea(attrs={"rows": 5}),
            "published_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "tags": forms.SelectMultiple(attrs={"size": 6}),
            "countries": forms.SelectMultiple(attrs={"size": 8}),
            "organizations": forms.SelectMultiple(attrs={"size": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("tags", "countries", "organizations"):
            self.fields[name].help_text = "Ctrl/⌘-click to select several."
        # Languages come from the Settings page. Keep the article's current language
        # selectable even if it has since been removed from the list.
        site = SiteSettings.load()
        self.default_language = site.default_language
        choices = site.language_choices()
        current = self.instance.language if self.instance.pk else None
        if current and current not in dict(choices):
            choices.append((current, language_name(current)))
        self.fields["language"] = forms.ChoiceField(
            label="Language",
            choices=choices,
            required=False,
            initial=current or site.default_language,
        )

    def clean_language(self):
        return self.cleaned_data.get("language") or self.default_language

    def publish_fields(self):
        return [self[name] for name in self.fields if name.startswith("post_")]


DATETIME_LOCAL = "%Y-%m-%dT%H:%M"


class ArticleCreateForm(ArticleForm):
    """The add form also lets the user set when the article counts as added."""

    class Meta(ArticleForm.Meta):
        fields = [*ArticleForm.Meta.fields, "created_at"]
        widgets = {
            **ArticleForm.Meta.widgets,
            "created_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format=DATETIME_LOCAL
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["created_at"]
        field.required = False
        field.input_formats = [DATETIME_LOCAL, *forms.DateTimeField.input_formats]
        field.help_text = "Leave empty to use the current time."

    def clean_created_at(self):
        value = self.cleaned_data.get("created_at")
        if value is None:
            return timezone.now()
        if value > timezone.now() + timezone.timedelta(minutes=5):
            raise forms.ValidationError("The added date can't be in the future.")
        return value


class TagForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = ["name"]


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name", "website"]


class PublisherForm(forms.ModelForm):
    class Meta:
        model = Publisher
        fields = ["name", "website", "alternative_website", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}

    def clean(self):
        cleaned = super().clean()
        seen = set()
        for field in ("website", "alternative_website"):
            domain = url_domain(cleaned.get(field))
            if not domain:
                continue
            if domain in seen:
                self.add_error(field, "This is the same domain as the website.")
                continue
            seen.add(domain)
            other = (
                Publisher.objects.filter(Q(domain=domain) | Q(alternative_domain=domain))
                .exclude(pk=self.instance.pk)
                .first()
            )
            if other:
                self.add_error(field, f"{domain} already belongs to the publisher “{other}”.")
        return cleaned


class SiteSettingsForm(forms.ModelForm):
    languages = forms.MultipleChoiceField(
        label="Article languages",
        choices=ALL_LANGUAGES,
        widget=forms.SelectMultiple(attrs={"size": 10}),
        help_text="Languages you can choose from for an article. Ctrl/⌘-click to select several.",
    )

    class Meta:
        model = SiteSettings
        fields = ["site_name", "site_description", "languages", "default_language"]
        widgets = {"site_description": forms.Textarea(attrs={"rows": 3})}
        help_texts = {"default_language": "Used for new articles."}

    def clean(self):
        cleaned = super().clean()
        languages, default = cleaned.get("languages"), cleaned.get("default_language")
        if languages and default and default not in languages:
            self.add_error(
                "default_language", "The default language must be one of the article languages."
            )
        return cleaned

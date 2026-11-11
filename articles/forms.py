from django import forms

from .models import Article, Organization, SiteSettings, Tag


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
    class Meta:
        model = Article
        fields = ["url", "title", "description", "image_url", "tags", "countries", "organizations"]
        labels = {"url": "URL", "image_url": "Photo URL"}
        widgets = {
            "url": forms.URLInput(attrs={"placeholder": "https://…"}),
            "description": forms.Textarea(attrs={"rows": 5}),
            "tags": forms.SelectMultiple(attrs={"size": 6}),
            "countries": forms.SelectMultiple(attrs={"size": 8}),
            "organizations": forms.SelectMultiple(attrs={"size": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("tags", "countries", "organizations"):
            self.fields[name].help_text = "Ctrl/⌘-click to select several."

    def publish_fields(self):
        return [self[name] for name in self.fields if name.startswith("post_")]


class TagForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = ["name"]


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name", "website"]


class SiteSettingsForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = ["site_name"]

from urllib.parse import urlparse

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


def unique_slug(instance, value, max_length=100):
    """Build a slug from `value` that is unique for the instance's model."""
    base = slugify(value)[:max_length] or "item"
    slug = base
    model = type(instance)
    n = 2
    while model.objects.filter(slug=slug).exclude(pk=instance.pk).exists():
        suffix = f"-{n}"
        slug = f"{base[: max_length - len(suffix)]}{suffix}"
        n += 1
    return slug


class SluggedModel(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        super().save(*args, **kwargs)


class Tag(SluggedModel):
    class Meta(SluggedModel.Meta):
        pass

    def get_absolute_url(self):
        return reverse("articles:tag", args=[self.slug])


class Organization(SluggedModel):
    website = models.URLField(blank=True)

    class Meta(SluggedModel.Meta):
        pass

    def get_absolute_url(self):
        return reverse("articles:organization", args=[self.slug])


class Country(models.Model):
    """ISO 3166-1 countries, pre-populated by a data migration."""

    code = models.CharField(max_length=2, unique=True)
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "countries"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("articles:country", args=[self.code.lower()])

    @property
    def flag(self):
        """Emoji flag built from the regional indicator symbols."""
        return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in self.code.upper())


class ArticleQuerySet(models.QuerySet):
    def with_relations(self):
        return self.select_related("added_by").prefetch_related(
            "tags", "countries", "organizations"
        )


class Article(models.Model):
    url = models.URLField(max_length=2000, unique=True)
    title = models.CharField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    image_url = models.URLField(max_length=2000, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="articles")
    countries = models.ManyToManyField(Country, blank=True, related_name="articles")
    organizations = models.ManyToManyField(Organization, blank=True, related_name="articles")
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="articles",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ArticleQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.display_title

    def get_absolute_url(self):
        return reverse("articles:article", args=[self.pk])

    @property
    def display_title(self):
        return self.title or self.url

    @property
    def domain(self):
        host = urlparse(self.url).hostname or ""
        return host.removeprefix("www.")


class SiteSettings(models.Model):
    """General website settings (a single row, pk=1)."""

    DEFAULT_NAME = "Charlie"

    site_name = models.CharField(
        "Website name",
        max_length=100,
        default=DEFAULT_NAME,
        help_text="Shown in the header, browser tabs and RSS feeds.",
    )

    class Meta:
        verbose_name = verbose_name_plural = "site settings"

    def __str__(self):
        return self.site_name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


def site_name():
    return SiteSettings.load().site_name

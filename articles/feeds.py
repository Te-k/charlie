import mimetypes
from urllib.parse import urlparse

from django.contrib.syndication.views import Feed
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.feedgenerator import Rss201rev2Feed

from .models import Article, Country, Organization, Publisher, Tag, site_name

FEED_SIZE = 50


class LatestArticlesFeed(Feed):
    feed_type = Rss201rev2Feed

    def title(self, obj=None):
        return f"{site_name()} – latest articles"

    description = "Interesting articles, newest first."

    def link(self, obj=None):
        return reverse("articles:home")

    def get_articles(self, obj):
        return Article.objects.all()

    def items(self, obj=None):
        return self.get_articles(obj).prefetch_related("tags")[:FEED_SIZE]

    def item_title(self, item):
        return item.display_title

    def item_description(self, item):
        return item.description

    def item_link(self, item):
        return item.url

    def item_guid(self, item):
        return self.request.build_absolute_uri(item.get_absolute_url())

    item_guid_is_permalink = True

    def item_pubdate(self, item):
        return item.created_at

    def item_updateddate(self, item):
        return item.updated_at

    def item_categories(self, item):
        return [tag.name for tag in item.tags.all()]

    def item_enclosure_url(self, item):
        return item.image_url or None

    def item_enclosure_length(self, item):
        return 0

    def item_enclosure_mime_type(self, item):
        guessed, _ = mimetypes.guess_type(urlparse(item.image_url).path)
        return guessed if guessed and guessed.startswith("image/") else "image/jpeg"

    def __call__(self, request, *args, **kwargs):
        self.request = request
        return super().__call__(request, *args, **kwargs)


class _FilteredFeed(LatestArticlesFeed):
    model = None
    lookup = "slug"
    relation = None
    label = ""

    def get_object(self, request, **kwargs):
        value = kwargs[self.lookup]
        if self.lookup == "code":
            value = value.upper()
        return get_object_or_404(self.model, **{self.lookup: value})

    def title(self, obj):
        return f"{site_name()} – {self.label}: {obj}"

    def description(self, obj):
        return f"Articles related to {self.label} {obj}."

    def link(self, obj):
        return obj.get_absolute_url()

    def get_articles(self, obj):
        return Article.objects.filter(**{self.relation: obj})


class TagFeed(_FilteredFeed):
    model, relation, label = Tag, "tags", "tag"


class OrganizationFeed(_FilteredFeed):
    model, relation, label = Organization, "organizations", "organization"


class PublisherFeed(_FilteredFeed):
    model, relation, label = Publisher, "publisher", "publisher"


class CountryFeed(_FilteredFeed):
    model, relation, label, lookup = Country, "countries", "country", "code"

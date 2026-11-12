from django.contrib import admin

from .models import Article, Country, Organization, Publisher, Tag


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ["name", "slug"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "website"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Publisher)
class PublisherAdmin(admin.ModelAdmin):
    list_display = ["name", "domain", "alternative_domain"]
    search_fields = ["name", "domain", "alternative_domain"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ["name", "code"]
    search_fields = ["name", "code"]


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ["display_title", "publisher", "added_by", "created_at"]
    list_filter = ["publisher", "language", "tags", "organizations", "created_at"]
    search_fields = ["title", "url", "description"]
    filter_horizontal = ["tags", "countries", "organizations"]
    readonly_fields = ["updated_at"]
    autocomplete_fields = ["publisher"]

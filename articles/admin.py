from django.contrib import admin

from .models import Article, Country, Organization, Tag


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


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ["name", "code"]
    search_fields = ["name", "code"]


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ["display_title", "url", "added_by", "created_at"]
    list_filter = ["tags", "organizations", "created_at"]
    search_fields = ["title", "url", "description"]
    filter_horizontal = ["tags", "countries", "organizations"]
    readonly_fields = ["created_at", "updated_at"]

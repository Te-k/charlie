from django.contrib import admin

from .models import SocialPost


@admin.register(SocialPost)
class SocialPostAdmin(admin.ModelAdmin):
    list_display = ["article", "network", "url", "posted_by", "created_at"]
    list_filter = ["network"]
    readonly_fields = ["created_at"]

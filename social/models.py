from django.conf import settings
from django.db import models

DEFAULT_MASTODON_TEMPLATE = "{title}\n\n{description}\n\n{url}\n\n{tags}"
DEFAULT_BLUESKY_TEMPLATE = "{title}\n\n{description}\n\n{tags}"

NETWORKS = {"mastodon": "Mastodon", "bluesky": "Bluesky"}


class SocialSettings(models.Model):
    """Site-wide Mastodon / Bluesky configuration (a single row, pk=1)."""

    VISIBILITY_CHOICES = [
        ("public", "Public"),
        ("unlisted", "Unlisted (quiet public)"),
        ("private", "Followers only"),
    ]

    mastodon_enabled = models.BooleanField("Enable Mastodon", default=False)
    mastodon_instance = models.URLField(
        "Instance URL", blank=True, help_text="For example https://mastodon.social"
    )
    mastodon_access_token = models.CharField(
        "Access token",
        max_length=255,
        blank=True,
        help_text="Preferences → Development → New application, with the "
        "“write:statuses” scope. Leave empty to keep the current token.",
    )
    mastodon_visibility = models.CharField(
        "Visibility", max_length=10, choices=VISIBILITY_CHOICES, default="public"
    )
    mastodon_template = models.TextField("Message format", default=DEFAULT_MASTODON_TEMPLATE)
    mastodon_default = models.BooleanField("Post new articles by default", default=True)

    bluesky_enabled = models.BooleanField("Enable Bluesky", default=False)
    bluesky_service = models.URLField(
        "PDS / service URL",
        default="https://bsky.social",
        help_text="Keep https://bsky.social unless you host your own PDS.",
    )
    bluesky_handle = models.CharField(
        "Handle", max_length=255, blank=True, help_text="For example alice.bsky.social"
    )
    bluesky_app_password = models.CharField(
        "App password",
        max_length=255,
        blank=True,
        help_text="Settings → Privacy and security → App passwords. "
        "Leave empty to keep the current password.",
    )
    bluesky_template = models.TextField("Message format", default=DEFAULT_BLUESKY_TEMPLATE)
    bluesky_link_card = models.BooleanField(
        "Attach a link card with the photo",
        default=True,
        help_text="Shows the article title, description and photo under the post.",
    )
    bluesky_default = models.BooleanField("Post new articles by default", default=True)

    class Meta:
        verbose_name = verbose_name_plural = "social settings"

    def __str__(self):
        return "Social settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def mastodon_ready(self):
        return bool(self.mastodon_enabled and self.mastodon_instance and self.mastodon_access_token)

    @property
    def bluesky_ready(self):
        return bool(self.bluesky_enabled and self.bluesky_handle and self.bluesky_app_password)

    def is_ready(self, network):
        return getattr(self, f"{network}_ready")

    def ready_networks(self):
        return [n for n in NETWORKS if self.is_ready(n)]


class SocialPost(models.Model):
    """A post published about an article on a social network."""

    article = models.ForeignKey(
        "articles.Article", on_delete=models.CASCADE, related_name="social_posts"
    )
    network = models.CharField(max_length=20, choices=list(NETWORKS.items()))
    url = models.URLField(max_length=500, blank=True)
    remote_id = models.CharField(max_length=500, blank=True)
    text = models.TextField()
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.get_network_display()} post for {self.article}"

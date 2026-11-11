from django import forms

from .models import SocialSettings

SECRET_FIELDS = ("mastodon_access_token", "bluesky_app_password")


class SocialSettingsForm(forms.ModelForm):
    class Meta:
        model = SocialSettings
        fields = [
            "mastodon_enabled",
            "mastodon_instance",
            "mastodon_access_token",
            "mastodon_visibility",
            "mastodon_template",
            "mastodon_default",
            "bluesky_enabled",
            "bluesky_service",
            "bluesky_handle",
            "bluesky_app_password",
            "bluesky_template",
            "bluesky_link_card",
            "bluesky_default",
        ]
        widgets = {
            "mastodon_access_token": forms.PasswordInput(
                render_value=False, attrs={"autocomplete": "off"}
            ),
            "bluesky_app_password": forms.PasswordInput(
                render_value=False, attrs={"autocomplete": "off"}
            ),
            "mastodon_template": forms.Textarea(attrs={"rows": 8, "class": "font-mono text-sm"}),
            "bluesky_template": forms.Textarea(attrs={"rows": 8, "class": "font-mono text-sm"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in SECRET_FIELDS:
            if getattr(self.instance, name):
                self.fields[name].widget.attrs["placeholder"] = "•••••••• (saved)"
        self.fields["bluesky_handle"].widget.attrs["placeholder"] = "alice.bsky.social"
        self.fields["mastodon_instance"].widget.attrs["placeholder"] = "https://mastodon.social"

    def clean(self):
        data = super().clean()
        # An empty secret field means "keep the saved value".
        for name in SECRET_FIELDS:
            if not data.get(name):
                data[name] = getattr(self.instance, name)
        for network, required in (
            ("mastodon", ("mastodon_instance", "mastodon_access_token")),
            ("bluesky", ("bluesky_handle", "bluesky_app_password")),
        ):
            if data.get(f"{network}_enabled"):
                for name in required:
                    if not data.get(name):
                        self.add_error(name, "Required to enable posting.")
        return data

    def section(self, prefix):
        return [self[name] for name in self.Meta.fields if name.startswith(prefix)]

    def mastodon_fields(self):
        return self.section("mastodon_")

    def bluesky_fields(self):
        return self.section("bluesky_")


def add_publish_fields(form, config, initial=False):
    """Add "Post on Mastodon/Bluesky" checkboxes to an article form."""
    from .models import NETWORKS

    for network in config.ready_networks():
        default = getattr(config, f"{network}_default")
        form.fields[f"post_{network}"] = forms.BooleanField(
            required=False, initial=default, label=f"Post on {NETWORKS[network]}"
        )

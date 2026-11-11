from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import UserPassesTestMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import UpdateView

from articles.forms import SiteSettingsForm
from articles.models import Article, SiteSettings

from . import publishers
from .forms import SocialSettingsForm
from .models import NETWORKS, SocialSettings


def example_article():
    article = Article.objects.order_by("-created_at").first()
    if article:
        return article
    article = Article(
        url="https://example.com/2026/11/an-interesting-article",
        title="An interesting article about something",
        description="A short summary of the article, as fetched from the page "
        "or written by hand when the article was added.",
    )
    article.example_tags = ["Machine Learning", "Privacy"]
    article.example_organizations = ["ACME"]
    article.example_countries = ["France"]
    return article


class SettingsView(UserPassesTestMixin, UpdateView):
    """Staff-only settings page: website name, plus Mastodon / Bluesky
    credentials and message formats. Both forms are saved together."""

    form_class = SocialSettingsForm
    template_name = "social/settings.html"
    success_url = reverse_lazy("social:settings")

    def test_func(self):
        return self.request.user.is_staff

    def get_object(self, queryset=None):
        return SocialSettings.load()

    def get_site_form(self):
        return SiteSettingsForm(
            data=self.request.POST if self.request.method == "POST" else None,
            instance=SiteSettings.load(),
            prefix="site",
        )

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form, site_form = self.get_form(), self.get_site_form()
        if form.is_valid() and site_form.is_valid():
            site_form.save()
            return self.form_valid(form)
        return self.render_to_response(self.get_context_data(form=form, site_form=site_form))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("site_form", self.get_site_form())
        article = example_article()
        link = self.request.build_absolute_uri(
            article.get_absolute_url() if article.pk else "/articles/1/"
        )
        config = self.object
        form = context["form"]
        if form.is_bound:  # preview what was just typed
            for network in NETWORKS:
                setattr(config, f"{network}_template", form.data.get(f"{network}_template", ""))
        context["previews"] = {
            network: {
                "text": (text := publishers.message_for(config, network, article, link)),
                "length": publishers.text_length(text, network),
                "limit": publishers.LIMITS[network],
            }
            for network in NETWORKS
        }
        context["preview_article"] = article
        context["placeholders"] = publishers.PLACEHOLDERS
        return context

    def form_valid(self, form):
        config = form.save()
        action = self.request.POST.get("action", "save")
        if action.startswith("test_"):
            network = action.removeprefix("test_")
            if network in NETWORKS and config.is_ready(network):
                try:
                    account = publishers.check_connection(config, network)
                    messages.success(self.request, f"{NETWORKS[network]}: connected as {account}.")
                except publishers.PublishError as exc:
                    messages.error(self.request, str(exc))
            else:
                messages.warning(
                    self.request, f"Enable and configure {NETWORKS.get(network, network)} first."
                )
        else:
            messages.success(self.request, "Settings saved.")
        return redirect(self.success_url)


def publish_with_messages(request, article, networks):
    """Publish `article` on each network, reporting the outcome as messages."""
    config = SocialSettings.load()
    link = request.build_absolute_uri(article.get_absolute_url())
    for network in networks:
        try:
            post = publishers.publish(config, network, article, link=link, user=request.user)
        except publishers.PublishError as exc:
            messages.error(request, f"Could not post on {NETWORKS[network]}. {exc}")
        else:
            messages.success(request, f"Posted on {NETWORKS[network]}: {post.url}")


@login_required
@require_POST
def share(request, pk, network):
    article = get_object_or_404(Article, pk=pk)
    if network not in NETWORKS:
        return redirect(article)
    publish_with_messages(request, article, [network])
    return redirect(article)

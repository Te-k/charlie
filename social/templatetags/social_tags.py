from django import template

from ..models import NETWORKS, SocialSettings

register = template.Library()


@register.inclusion_tag("social/_article_social.html", takes_context=True)
def article_social(context, article):
    """Existing posts for an article, plus buttons to post on configured networks."""
    request = context["request"]
    posts = list(article.social_posts.all())
    config = SocialSettings.load() if request.user.is_authenticated else None
    posted = {p.network for p in posts}
    networks = [
        {"code": n, "label": NETWORKS[n], "posted": n in posted}
        for n in (config.ready_networks() if config else [])
    ]
    return {
        "article": article,
        "posts": posts,
        "networks": networks,
        "request": request,
        "csrf_token": context.get("csrf_token"),
        "user": request.user,
    }

from urllib.parse import urlparse

from django.db import migrations
from django.utils.text import slugify


def domain(url):
    return ((urlparse(url or "").hostname or "").rstrip(".")).removeprefix("www.")


def link_articles(apps, schema_editor):
    """Give every existing article a publisher, one per domain, named after the domain."""
    Article = apps.get_model("articles", "Article")
    Publisher = apps.get_model("articles", "Publisher")
    by_domain = {}
    for article in Article.objects.filter(publisher__isnull=True):
        host = domain(article.url)
        if not host:
            continue
        if host not in by_domain:
            publisher = (
                Publisher.objects.filter(domain=host).first()
                or Publisher.objects.filter(alternative_domain=host).first()
            )
            if publisher is None:
                name, slug, n = host[:100], slugify(host.replace(".", " "))[:100] or "publisher", 2
                while Publisher.objects.filter(name=name).exists():
                    name = f"{host[:95]} {n}"
                    n += 1
                base, n = slug, 2
                while Publisher.objects.filter(slug=slug).exists():
                    slug = f"{base[:95]}-{n}"
                    n += 1
                parsed = urlparse(article.url)
                publisher = Publisher.objects.create(
                    name=name,
                    slug=slug,
                    website=f"{parsed.scheme}://{parsed.hostname}/",
                    domain=host,
                )
            by_domain[host] = publisher
        article.publisher = by_domain[host]
        article.save(update_fields=["publisher"])


class Migration(migrations.Migration):
    dependencies = [("articles", "0005_publisher")]

    operations = [migrations.RunPython(link_articles, migrations.RunPython.noop)]

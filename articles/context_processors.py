from .models import SiteSettings


def site(request):
    settings = SiteSettings.load()
    return {
        "site_name": settings.site_name,
        "site_description": settings.site_description,
        "default_language": settings.default_language,
    }

from .models import site_name


def site(request):
    return {"site_name": site_name()}

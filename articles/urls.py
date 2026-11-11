from django.urls import path, re_path
from django.views.generic import RedirectView

from . import feeds, views

app_name = "articles"

urlpatterns = [
    path("", views.ArticleListView.as_view(), name="home"),
    path("feed/", feeds.LatestArticlesFeed(), name="feed"),
    path("articles/add/", views.ArticleCreateView.as_view(), name="article_add"),
    path("articles/<int:pk>/", views.ArticleDetailView.as_view(), name="article"),
    path("articles/<int:pk>/edit/", views.ArticleUpdateView.as_view(), name="article_edit"),
    path("articles/<int:pk>/delete/", views.ArticleDeleteView.as_view(), name="article_delete"),
    path("tags/", views.TagIndexView.as_view(), name="tags"),
    path("tags/add/", views.TagCreateView.as_view(), name="tag_add"),
    path("tags/<slug:slug>/", views.TagArticlesView.as_view(), name="tag"),
    path("tags/<slug:slug>/feed/", feeds.TagFeed(), name="tag_feed"),
    path("organizations/", views.OrganizationIndexView.as_view(), name="organizations"),
    path("organizations/add/", views.OrganizationCreateView.as_view(), name="organization_add"),
    path(
        "organizations/<slug:slug>/", views.OrganizationArticlesView.as_view(), name="organization"
    ),
    path("organizations/<slug:slug>/feed/", feeds.OrganizationFeed(), name="organization_feed"),
    # Organizations used to be called companies: keep old links and feed subscriptions working.
    re_path(
        r"^companies/(?P<rest>.*)$",
        RedirectView.as_view(url="/organizations/%(rest)s", permanent=True, query_string=True),
    ),
    path("countries/", views.CountryIndexView.as_view(), name="countries"),
    path("countries/<str:code>/", views.CountryArticlesView.as_view(), name="country"),
    path("countries/<str:code>/feed/", feeds.CountryFeed(), name="country_feed"),
]

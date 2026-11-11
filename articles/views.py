from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.http import HttpResponseRedirect, QueryDict
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.functional import cached_property
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from social.forms import add_publish_fields
from social.models import SocialSettings
from social.views import publish_with_messages

from . import metadata
from .forms import (
    DATETIME_LOCAL,
    ArticleCreateForm,
    ArticleForm,
    ArticleUrlForm,
    OrganizationForm,
    PublisherForm,
    TagForm,
)
from .models import Article, Country, Organization, Publisher, Tag, url_domain


class ArticleListView(ListView):
    """Home page: all articles, newest first."""

    template_name = "articles/article_list.html"
    context_object_name = "articles"
    paginate_by = settings.ARTICLES_PER_PAGE

    def get_queryset(self):
        return Article.objects.with_relations()


class FilteredArticleListView(ArticleListView):
    """Articles linked to a tag, a country, an organization or a publisher."""

    model = None
    lookup = "slug"
    relation = None
    kind = None

    def get_object(self):
        value = self.kwargs[self.lookup]
        if self.lookup == "code":
            value = value.upper()
        return get_object_or_404(self.model, **{self.lookup: value})

    def get_queryset(self):
        self.object = self.get_object()
        return super().get_queryset().filter(**{self.relation: self.object})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_object"] = self.object
        context["filter_kind"] = self.kind
        context["feed_url"] = reverse(f"articles:{self.kind}_feed", args=[self.kwargs[self.lookup]])
        return context


class TagArticlesView(FilteredArticleListView):
    model, relation, kind = Tag, "tags", "tag"


class OrganizationArticlesView(FilteredArticleListView):
    model, relation, kind = Organization, "organizations", "organization"


class PublisherArticlesView(FilteredArticleListView):
    model, relation, kind = Publisher, "publisher", "publisher"


class CountryArticlesView(FilteredArticleListView):
    model, relation, kind, lookup = Country, "countries", "country", "code"


class IndexView(ListView):
    """List of tags / organizations / publishers / countries with their article counts."""

    template_name = "articles/index_list.html"
    context_object_name = "items"
    model = None
    title = ""

    def get_queryset(self):
        return self.model.objects.annotate(article_count=Count("articles")).order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = self.title
        context["add_url"] = getattr(self, "add_url", None)
        return context


class TagIndexView(IndexView):
    model, title, add_url = Tag, "Tags", reverse_lazy("articles:tag_add")


class OrganizationIndexView(IndexView):
    model, title, add_url = Organization, "Organizations", reverse_lazy("articles:organization_add")


class PublisherIndexView(IndexView):
    model, title, add_url = Publisher, "Publishers", reverse_lazy("articles:publisher_add")


class CountryIndexView(IndexView):
    model, title = Country, "Countries"


class ArticleDetailView(DetailView):
    model = Article
    context_object_name = "article"

    def get_queryset(self):
        return Article.objects.with_relations()


METADATA_FIELDS = ("title", "description", "image_url", "published_on")


class ArticleFormMixin(LoginRequiredMixin):
    """Shared by add and edit.

    Posting with ``action=fetch`` fetches the title, description and photo from
    the URL and shows them in the form for review; nothing is saved until the
    user clicks "Save".
    """

    model = Article
    form_class = ArticleForm

    def post(self, request, *args, **kwargs):
        if request.POST.get("action") == "fetch":
            return self.fetch_and_review(request.POST.copy())
        return super().post(request, *args, **kwargs)

    def fetch_and_review(self, data):
        meta = metadata.fetch_metadata(data.get("url", "").strip())
        found = False
        for field in METADATA_FIELDS:
            value = meta.get(field)
            if value:
                max_length = Article._meta.get_field(field).max_length
                data[field] = value[:max_length] if max_length else value
                found = True
        # Find the publisher again: the URL may have changed.
        url = data.get("url", "").strip()
        publisher = Publisher.objects.for_url(url)
        data["publisher"] = str(publisher.pk) if publisher else ""
        data["publisher_name"] = (meta.get("site_name") or "")[:100]
        if found:
            messages.info(
                self.request,
                "Details fetched from the page. Check and edit them, then save.",
            )
        else:
            messages.warning(
                self.request,
                "Could not fetch details from the page. Please fill them in yourself.",
            )
        form = self.get_form_class()(data=data, instance=self.object)
        self.extend_form(form)
        return self.render_to_response(self.get_context_data(form=form, fetched=True))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context["form"]
        # Tell the user when saving will create a new publisher.
        if form.is_bound and not form["publisher"].value():
            url = form["url"].value() or ""
            domain = url_domain(url)
            if domain and not Publisher.objects.for_url(url):
                context["new_publisher"] = form["publisher_name"].value() or domain
        return context

    def extend_form(self, form):
        """Hook to add extra fields to the article form."""

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        self.extend_form(form)
        return form

    def after_save(self, form, article):
        """Hook called once the article and its relations are saved."""

    def form_valid(self, form):
        article = form.save(commit=False)
        if "url" in form.changed_data and "publisher" not in form.changed_data:
            article.publisher = None  # the URL changed: find the publisher again
        article.publisher_name = form.cleaned_data.get("publisher_name", "")
        if not article.added_by_id:
            article.added_by = self.request.user
        article.save()
        form.save_m2m()
        self.object = article
        messages.success(self.request, f"Article “{article.display_title}” saved.")
        self.after_save(form, article)
        return HttpResponseRedirect(self.get_success_url())


class ArticleCreateView(ArticleFormMixin, CreateView):
    """Step 1: ask for the URL. Step 2: review the fetched details and save.

    ``/articles/add/?url=…`` jumps straight to step 2 (handy for bookmarklets).
    """

    def get(self, request, *args, **kwargs):
        self.object = None
        if "url" in request.GET:
            return self.step_one(ArticleUrlForm(request.GET))
        return self.step_one(ArticleUrlForm())

    def post(self, request, *args, **kwargs):
        self.object = None
        if request.POST.get("action") == "fetch" and "title" not in request.POST:
            return self.step_one(ArticleUrlForm(request.POST))
        return super().post(request, *args, **kwargs)

    form_class = ArticleCreateForm

    def extend_form(self, form):
        add_publish_fields(form, self.social_config)

    @cached_property
    def social_config(self):
        return SocialSettings.load()

    def after_save(self, form, article):
        networks = [
            n for n in self.social_config.ready_networks() if form.cleaned_data.get(f"post_{n}")
        ]
        publish_with_messages(self.request, article, networks)

    def step_one(self, url_form):
        if url_form.is_bound and url_form.is_valid():
            data = QueryDict(mutable=True)
            data["url"] = url_form.cleaned_data["url"]
            data["created_at"] = timezone.localtime().strftime(DATETIME_LOCAL)
            # Pre-check the "Post on …" boxes according to the settings.
            for network in self.social_config.ready_networks():
                if getattr(self.social_config, f"{network}_default"):
                    data[f"post_{network}"] = "on"
            return self.fetch_and_review(data)
        return render(
            self.request,
            "articles/article_add_url.html",
            {
                "form": url_form,
                "existing": getattr(url_form, "existing_article", None),
            },
        )


class ArticleUpdateView(ArticleFormMixin, UpdateView):
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super().post(request, *args, **kwargs)


class ArticleDeleteView(LoginRequiredMixin, DeleteView):
    model = Article
    success_url = reverse_lazy("articles:home")

    def form_valid(self, form):
        messages.success(self.request, f"Article “{self.object.display_title}” deleted.")
        return super().form_valid(form)


class SimpleFormMixin(LoginRequiredMixin):
    template_name = "articles/simple_form.html"
    title = ""
    submit_label = "Add"

    def get_cancel_url(self):
        return self.cancel_url

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = self.title
        context["submit_label"] = self.submit_label
        context["cancel_url"] = self.get_cancel_url()
        return context


class SimpleCreateView(SimpleFormMixin, CreateView):
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"“{self.object}” added.")
        return response


class TagCreateView(SimpleCreateView):
    model, form_class, title = Tag, TagForm, "Add a tag"
    cancel_url = reverse_lazy("articles:tags")


class OrganizationCreateView(SimpleCreateView):
    model, form_class, title = Organization, OrganizationForm, "Add an organization"
    cancel_url = reverse_lazy("articles:organizations")


class PublisherCreateView(SimpleCreateView):
    model, form_class, title = Publisher, PublisherForm, "Add a publisher"
    cancel_url = reverse_lazy("articles:publishers")


class PublisherUpdateView(SimpleFormMixin, UpdateView):
    model, form_class, title, submit_label = Publisher, PublisherForm, "Edit publisher", "Save"

    def get_cancel_url(self):
        return self.object.get_absolute_url()

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"“{self.object}” saved.")
        return response

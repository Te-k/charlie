from django.db import migrations


def load_countries(apps, schema_editor):
    from django_countries import countries

    Country = apps.get_model("articles", "Country")
    existing = set(Country.objects.values_list("code", flat=True))
    Country.objects.bulk_create(
        Country(code=code, name=str(name))
        for code, name in countries
        if code not in existing
    )


class Migration(migrations.Migration):
    dependencies = [("articles", "0001_initial")]

    operations = [migrations.RunPython(load_countries, migrations.RunPython.noop)]

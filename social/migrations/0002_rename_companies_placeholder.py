from django.db import migrations


def forwards(apps, schema_editor):
    rename(apps, "{companies}", "{organizations}")


def backwards(apps, schema_editor):
    rename(apps, "{organizations}", "{companies}")


def rename(apps, old, new):
    SocialSettings = apps.get_model("social", "SocialSettings")
    for obj in SocialSettings.objects.all():
        obj.mastodon_template = obj.mastodon_template.replace(old, new)
        obj.bluesky_template = obj.bluesky_template.replace(old, new)
        obj.save(update_fields=["mastodon_template", "bluesky_template"])


class Migration(migrations.Migration):
    dependencies = [("social", "0001_initial")]

    operations = [migrations.RunPython(forwards, backwards)]

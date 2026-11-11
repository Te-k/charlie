from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("articles", "0003_site_settings"),
    ]

    operations = [
        migrations.RenameModel("Company", "Organization"),
        migrations.AlterModelOptions(
            name="organization",
            options={"ordering": ["name"]},
        ),
        migrations.RenameField("article", "companies", "organizations"),
    ]

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("store", "0013_remove_base64_product_media"),
    ]

    operations = [
        migrations.CreateModel(
            name="Credential",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("service", models.CharField(db_index=True, max_length=100)),
                ("account", models.CharField(blank=True, default="", max_length=150)),
                ("credential_type", models.CharField(blank=True, default="", max_length=100)),
                ("description", models.CharField(blank=True, default="", max_length=500)),
                ("encrypted_value", models.BinaryField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "ordering": ["service", "account", "credential_type", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("service", "account", "credential_type"),
                        name="credential_unique_entry",
                    )
                ],
                "indexes": [
                    models.Index(fields=["service", "account"], name="credential_lookup_idx"),
                ],
            },
        ),
    ]

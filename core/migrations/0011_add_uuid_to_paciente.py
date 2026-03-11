import uuid
from django.db import migrations, models


def poblar_uuid_pacientes(apps, schema_editor):
    Paciente = apps.get_model("core", "Paciente")
    for paciente in Paciente.objects.filter(uuid__isnull=True).iterator():
        paciente.uuid = uuid.uuid4()
        paciente.save(update_fields=["uuid"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "00XX_MIGRACION_ANTERIOR"),
    ]

    operations = [
        migrations.AddField(
            model_name="paciente",
            name="uuid",
            field=models.UUIDField(
                null=True,
                editable=False,
                db_index=True,
            ),
        ),
        migrations.RunPython(poblar_uuid_pacientes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="paciente",
            name="uuid",
            field=models.UUIDField(
                default=uuid.uuid4,
                unique=True,
                editable=False,
                db_index=True,
            ),
        ),
    ]
"""Face records made with the old Facenet512 model cannot be compared with ArcFace
embeddings (both are 512 numbers, so a comparison would silently give nonsense).
Clear them; those students register their face again."""

from django.db import migrations


def clear_faces(apps, schema_editor):
    Voter = apps.get_model("voting", "Voter")
    AuditLog = apps.get_model("voting", "AuditLog")
    stale = Voter.objects.exclude(face_embedding__isnull=True)
    for voter in stale:
        AuditLog.objects.create(
            action="registration_reset", reg_number=voter.reg_number,
            detail="face model changed to ArcFace; register again",
        )
    stale.update(face_embedding=None, registered_at=None, face_photo="")


class Migration(migrations.Migration):
    dependencies = [("voting", "0001_initial")]
    operations = [migrations.RunPython(clear_faces, migrations.RunPython.noop)]

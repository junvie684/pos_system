from django.db import migrations, models
from django.db.models import Q


def grant_to_admins_and_managers(apps, schema_editor):
    """Admins and managers keep the Dashboard they have today; cashiers lose it."""
    UserProfile = apps.get_model('accounts', 'UserProfile')
    (UserProfile._base_manager
        .filter(Q(user__is_staff=True) | Q(user__is_superuser=True))
        .update(can_access_dashboard=True))


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_userprofile_tenant_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='can_access_dashboard',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(grant_to_admins_and_managers, migrations.RunPython.noop),
    ]

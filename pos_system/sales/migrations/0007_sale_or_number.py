from django.db import migrations, models


def backfill_or_numbers(apps, schema_editor):
    """Number existing paid sales per store, oldest first."""
    Sale = apps.get_model('sales', 'Sale')
    counters = {}
    paid = (Sale.objects.filter(status__in=['completed', 'refunded'])
            .order_by('tenant_id', 'created_at', 'pk'))
    for sale in paid.iterator():
        counters[sale.tenant_id] = counters.get(sale.tenant_id, 0) + 1
        sale.or_number = counters[sale.tenant_id]
        sale.save(update_fields=['or_number'])


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0006_sale_idempotency_key'),
        ('tenants', '__first__'),
    ]

    operations = [
        migrations.AddField(
            model_name='sale',
            name='or_number',
            field=models.PositiveIntegerField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(backfill_or_numbers, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='sale',
            constraint=models.UniqueConstraint(fields=('tenant_id', 'or_number'), name='unique_or_number_per_store'),
        ),
    ]

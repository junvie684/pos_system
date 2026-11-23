"""
Move paid sales past each store's retention period into the pos_archive database.

Run it every hour (e.g. a Railway cron service with schedule `0 * * * *`:
`python manage.py archive_sales`). Each store with automatic archiving on is
archived only at its own hour (archive_hour, store time) and only on days its
run is due (every archive_every_days days, counted from its last run).
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from archive.services import archive_store, eligible_sales
from tenants.models import Tenant


class Command(BaseCommand):
    help = "Archive paid sales older than each store's retention period."

    def add_arguments(self, parser):
        parser.add_argument('--store', metavar='SLUG',
                            help='Archive this store now, even if automatic archiving is off.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Only report how many sales would move.')

    def handle(self, *args, store=None, dry_run=False, **options):
        if store:
            stores = Tenant.objects.filter(slug=store)
            if not stores.exists():
                raise CommandError(f'No store with slug "{store}".')
        else:
            stores = Tenant.objects.filter(auto_archive=True)

        total = 0
        for tenant in stores.order_by('name'):
            if not store and not tenant.archive_is_due():
                self.stdout.write(f'{tenant.slug}: next run {timezone.localtime(tenant.next_archive_run()):%Y-%m-%d %H:%M} '
                                  f'(every {tenant.archive_every_days} day(s) at {tenant.archive_hour:02d}:00)')
                continue
            if dry_run:
                n = eligible_sales(tenant).count()
                self.stdout.write(f'{tenant.slug}: {n} sale(s) would move '
                                  f'(retention {tenant.retention_days} days)')
            else:
                n = archive_store(tenant)
                self.stdout.write(f'{tenant.slug}: moved {n} sale(s)')
            total += n
        verb = 'would move' if dry_run else 'moved'
        self.stdout.write(self.style.SUCCESS(f'Done: {verb} {total} sale(s) in total.'))

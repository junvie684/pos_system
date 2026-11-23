# tenants/models.py
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
import uuid

# Paid sales older than this many days move to the pos_archive database.
# The floor keeps refunds, the cash closing report and month-over-month
# comparisons working on the main database.
RETENTION_MIN_DAYS = 90
RETENTION_MAX_DAYS = 3650
RETENTION_DEFAULT_DAYS = 365
# How often automatic archiving runs for a store, in days (1 = every night).
ARCHIVE_EVERY_MIN_DAYS = 1
ARCHIVE_EVERY_MAX_DAYS = 90


class Tenant(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    owner = models.EmailField()
    address = models.CharField(max_length=500, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    tin = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # ── Data retention ──
    retention_days   = models.PositiveIntegerField(
        default=RETENTION_DEFAULT_DAYS,
        validators=[MinValueValidator(RETENTION_MIN_DAYS), MaxValueValidator(RETENTION_MAX_DAYS)],
        help_text='Paid sales older than this many days move to the archive database.',
    )
    auto_archive     = models.BooleanField(
        default=False, help_text='Archive automatically when the nightly archive job runs.')
    archive_every_days = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(ARCHIVE_EVERY_MIN_DAYS), MaxValueValidator(ARCHIVE_EVERY_MAX_DAYS)],
        help_text='Automatic archiving runs every this many days (1 = every night).',
    )
    archive_hour     = models.PositiveSmallIntegerField(
        default=2, validators=[MaxValueValidator(23)],
        help_text='Hour of the day (store time, 0-23) automatic archiving runs.',
    )
    last_archived_at = models.DateTimeField(null=True, blank=True)
    last_archive_count = models.PositiveIntegerField(default=0)

    # Highest OR number ever issued. Archived sales leave the main database, so
    # the next number can't be read from the sales table alone.
    last_or_number   = models.PositiveIntegerField(default=0)

    class Meta:
        # Remove the custom permissions list entirely.
        # Django automatically creates these for every model:
        #   tenants.add_tenant
        #   tenants.change_tenant
        #   tenants.delete_tenant
        #   tenants.view_tenant
        pass

    def next_archive_date(self):
        """First local date the next automatic run may happen, or None if any
        date will do (never archived). Counted from the last run, manual or
        automatic."""
        if not self.last_archived_at:
            return None
        from datetime import timedelta
        from django.utils import timezone
        return timezone.localdate(self.last_archived_at) + timedelta(days=self.archive_every_days)

    def archive_is_due(self, now=None):
        """True during the store's archive hour on a day the run is due. The
        archive job runs every hour; each store only takes the run at its hour."""
        from django.utils import timezone
        local = timezone.localtime(now)
        due = self.next_archive_date()
        return local.hour == self.archive_hour and (due is None or local.date() >= due)

    def next_archive_run(self, now=None):
        """Local datetime of the next automatic run (if auto-archive is on)."""
        from datetime import datetime, time, timedelta
        from django.utils import timezone
        local = timezone.localtime(now)
        day = max(self.next_archive_date() or local.date(), local.date())
        if day == local.date() and local.hour > self.archive_hour:
            day += timedelta(days=1)
        return timezone.make_aware(datetime.combine(day, time(self.archive_hour)))

    def __str__(self):
        return self.name
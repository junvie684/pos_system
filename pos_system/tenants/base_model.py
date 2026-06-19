
from django.db import models
from .middleware import get_current_tenant_id

import uuid

class TenantManager(models.Manager):
    def get_queryset(self):
        qs = super().get_queryset()
        tenant_id = get_current_tenant_id()

        if not tenant_id:
            return qs

        # Guard against "None" string or invalid UUIDs
        try:
            uuid.UUID(str(tenant_id))
        except (ValueError, AttributeError):
            return qs

        return qs.filter(tenant_id=tenant_id)

class TenantModel(models.Model):
    tenant_id   = models.UUIDField(db_index=True, null=True, blank=True)
    objects     = TenantManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.tenant_id:
            self.tenant_id = get_current_tenant_id()
        super().save(*args, **kwargs)
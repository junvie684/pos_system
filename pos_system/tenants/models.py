# tenants/models.py
from django.db import models
import uuid


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

    class Meta:
        # Remove the custom permissions list entirely.
        # Django automatically creates these for every model:
        #   tenants.add_tenant
        #   tenants.change_tenant
        #   tenants.delete_tenant
        #   tenants.view_tenant
        pass

    def __str__(self):
        return self.name
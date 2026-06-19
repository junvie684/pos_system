from django.db import models
from tenants.base_model import TenantModel


class Customer(TenantModel):
    name       = models.CharField(max_length=200)
    email      = models.EmailField(blank=True, null=True)
    phone      = models.CharField(max_length=20, blank=True)
    address    = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('tenant_id', 'email')

    def __str__(self):
        return self.name
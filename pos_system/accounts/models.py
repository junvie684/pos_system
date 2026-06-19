from django.db import models
from django.contrib.auth.models import User
from tenants.base_model import TenantModel


class UserProfile(TenantModel):
    user                        = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    can_access_products         = models.BooleanField(default=False)
    can_access_categories       = models.BooleanField(default=False)
    can_access_reports          = models.BooleanField(default=False)
    can_access_user_management  = models.BooleanField(default=False)
    can_access_pending_sales    = models.BooleanField(default=False)
    can_access_shift_report     = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} Profile"

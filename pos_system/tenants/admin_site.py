from django.contrib import admin
from django.contrib.admin.apps import AdminConfig

from .decorators import is_platform_admin


class PlatformAdminSite(admin.AdminSite):
    """Django admin sees every store's data, so only platform admins may enter."""

    @property
    def login_form(self):
        from accounts.throttle import ThrottledAdminAuthenticationForm
        return ThrottledAdminAuthenticationForm

    def has_permission(self, request):
        return super().has_permission(request) and is_platform_admin(request.user)


class PlatformAdminConfig(AdminConfig):
    default_site = 'tenants.admin_site.PlatformAdminSite'

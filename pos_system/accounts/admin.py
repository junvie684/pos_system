from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    model   = UserProfile
    extra   = 0
    readonly_fields = ('tenant_id',)

    def get_queryset(self, request):
        return UserProfile.all_objects.all()   # bypass TenantManager


class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ('username', 'email', 'get_store', 'is_staff', 'is_active')

    def get_store(self, obj):
        try:
            profile = UserProfile.all_objects.get(user=obj)
            from tenants.models import Tenant
            tenant = Tenant.objects.get(id=profile.tenant_id)
            return tenant.name
        except Exception:
            return '—'
    get_store.short_description = 'Store'


# Re-register User with our extended admin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Count
from .models import Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display  = ('name', 'slug', 'owner', 'is_active', 'created_at', 'user_count', 'actions_column')
    list_filter   = ('is_active',)
    search_fields = ('name', 'slug', 'owner')
    ordering      = ('name',)
    readonly_fields = ('id', 'created_at')

    fieldsets = (
        ('Store info', {
            'fields': ('id', 'name', 'slug', 'owner', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('created_at',)
        }),
    )

    def get_queryset(self, request):
        # Admin sees ALL tenants — bypass TenantManager
        return Tenant.objects.all().annotate(_user_count=Count('id'))

    def user_count(self, obj):
        from accounts.models import UserProfile
        count = UserProfile.all_objects.filter(tenant_id=obj.id).count()
        return count
    user_count.short_description = 'Users'

    def actions_column(self, obj):
        toggle_url = reverse('admin:tenants_tenant_change', args=[obj.pk])
        color = 'green' if obj.is_active else 'red'
        label = 'Active' if obj.is_active else 'Inactive'
        return format_html(
            '<span style="color:{}">● {}</span>',
            color, label
        )
    actions_column.short_description = 'Status'

    actions = ['activate_stores', 'deactivate_stores']

    def activate_stores(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} store(s) activated.')
    activate_stores.short_description = 'Activate selected stores'

    def deactivate_stores(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} store(s) deactivated.')
    deactivate_stores.short_description = 'Deactivate selected stores'
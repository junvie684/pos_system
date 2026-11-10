from django.contrib import admin
from tenants.admin_mixins import AllStoresAdminMixin
from .models import Customer


@admin.register(Customer)
class CustomerAdmin(AllStoresAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'tenant_id')
    readonly_fields = ('tenant_id',)

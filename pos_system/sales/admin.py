from django.contrib import admin
from tenants.admin_mixins import AllStoresAdminMixin
from .models import Sale, SaleItem


class SaleItemInline(AllStoresAdminMixin, admin.TabularInline):
    model  = SaleItem
    extra  = 0
    readonly_fields = ('product', 'quantity', 'unit_price', 'subtotal')

    def subtotal(self, obj):
        return obj.subtotal
    subtotal.short_description = 'Subtotal'

    def get_queryset(self, request):
        return SaleItem.all_objects.all()


@admin.register(Sale)
class SaleAdmin(AllStoresAdminMixin, admin.ModelAdmin):
    list_display  = ('pk', 'get_store', 'cashier', 'customer', 'admin_total', 'status', 'created_at')
    list_filter   = ('status',)
    search_fields = ('cashier__username', 'customer__name')
    readonly_fields = ('tenant_id', 'created_at')
    inlines       = (SaleItemInline,)

    def get_queryset(self, request):
        return Sale.all_objects.all()   # ← see ALL stores' sales

    def admin_total(self, obj):
        # Sale.total walks a store-scoped reverse manager, which is empty here.
        return sum(i.subtotal for i in SaleItem.all_objects.filter(sale=obj))
    admin_total.short_description = 'Total'

    def get_store(self, obj):
        try:
            from tenants.models import Tenant
            return Tenant.objects.get(id=obj.tenant_id).name
        except Exception:
            return '—'
    get_store.short_description = 'Store'
from django.contrib import admin
from .models import Sale, SaleItem


class SaleItemInline(admin.TabularInline):
    model  = SaleItem
    extra  = 0
    readonly_fields = ('product', 'quantity', 'unit_price', 'subtotal')

    def subtotal(self, obj):
        return obj.subtotal
    subtotal.short_description = 'Subtotal'

    def get_queryset(self, request):
        return SaleItem.all_objects.all()


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display  = ('pk', 'get_store', 'cashier', 'customer', 'total', 'status', 'created_at')
    list_filter   = ('status',)
    search_fields = ('cashier__username', 'customer__name')
    readonly_fields = ('tenant_id', 'created_at')
    inlines       = (SaleItemInline,)

    def get_queryset(self, request):
        return Sale.all_objects.all()   # ← see ALL stores' sales

    def get_store(self, obj):
        try:
            from tenants.models import Tenant
            return Tenant.objects.get(id=obj.tenant_id).name
        except Exception:
            return '—'
    get_store.short_description = 'Store'
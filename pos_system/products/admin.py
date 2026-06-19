from django.contrib import admin
from .models import Product, Category


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display  = ('name', 'get_store', 'category', 'price', 'stock', 'is_active')
    list_filter   = ('is_active', 'category')
    search_fields = ('name', 'barcode')
    readonly_fields = ('tenant_id',)

    def get_queryset(self, request):
        return Product.all_objects.all()

    def get_store(self, obj):
        try:
            from tenants.models import Tenant
            return Tenant.objects.get(id=obj.tenant_id).name
        except Exception:
            return '—'
    get_store.short_description = 'Store'


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display  = ('name', 'get_store')
    readonly_fields = ('tenant_id',)

    def get_queryset(self, request):
        return Category.all_objects.all()

    def get_store(self, obj):
        try:
            from tenants.models import Tenant
            return Tenant.objects.get(id=obj.tenant_id).name
        except Exception:
            return '—'
    get_store.short_description = 'Store'
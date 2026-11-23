# price_checker/views.py
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET
from products.models import Product
from tenants.models import Tenant

# The kiosk is public, so it shows a stock band rather than the exact count.
LOW_STOCK_AT = 5


def stock_status(stock):
    return 'out' if stock <= 0 else 'low' if stock <= LOW_STOCK_AT else 'in'


def kiosk(request, store_slug):
    tenant = get_object_or_404(Tenant, slug=store_slug, is_active=True)
    return render(request, 'price_checker/kiosk.html', {'store': tenant})


@require_GET
def api_lookup(request, store_slug, barcode):
    # The store comes from the URL: the kiosk is used without signing in.
    tenant = get_object_or_404(Tenant, slug=store_slug, is_active=True)

    try:
        # Use all_objects to bypass TenantManager, filter manually
        product = Product.all_objects.get(
            barcode=barcode,
            is_active=True,
            tenant_id=tenant.id          # ← explicit tenant filter
        )
    except Product.DoesNotExist:
        return JsonResponse({'found': False}, status=404)

    return JsonResponse({
        'found'         : True,
        'name'          : product.name,
        'price'         : str(product.price),
        'stock_status'  : stock_status(product.stock),
        'image'         : request.build_absolute_uri(product.image.url) if product.image else None,
        'promo_text'    : None,
    })
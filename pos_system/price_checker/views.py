# price_checker/views.py
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt
from products.models import Product
from tenants.models import Tenant
import threading

_thread_locals = threading.local()

def kiosk(request, store_slug):
    tenant = get_object_or_404(Tenant, slug=store_slug, is_active=True)
    return render(request, 'price_checker/kiosk.html', {'store': tenant})

@csrf_exempt
@require_GET
def api_lookup(request, store_slug, barcode):
    # Identify store from URL instead of JWT
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
        'stock'         : product.stock,
        'low_stock'     : product.stock <= 5,
        'image'         : request.build_absolute_uri(product.image.url) if product.image else None,
        'promo_text'    : None,
    })
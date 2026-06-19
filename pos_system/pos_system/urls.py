from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('platform/',       include('tenants.admin_urls')),
    path('', include('sales.urls')),
    path('products/', include('products.urls')),
    path('customers/', include('customers.urls')),
    path('reports/', include('reports.urls')),
    path('price-check/', include('price_checker.urls')),
    path('stores/',         include('tenants.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
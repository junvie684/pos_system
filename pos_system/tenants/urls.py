from django.urls import path, include
from . import views

app_name = 'tenants'

urlpatterns = [
    path('api/login/',      views.store_login,    name='store_login'),
    path('api/stores/',     views.store_list,     name='store_list'),
    path('platform/',  include('tenants.admin_urls')),
]
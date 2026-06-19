# price_checker/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('<slug:store_slug>/',                          views.kiosk,      name='kiosk'),
    path('<slug:store_slug>/api/<str:barcode>/',        views.api_lookup, name='api_lookup'),
]
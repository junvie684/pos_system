from django.urls import path
from . import views
app_name = 'reports'
urlpatterns = [
    path('', views.daily_report, name='daily'),
    path('monthly/', views.monthly_report, name='monthly'),
    path('analytics/', views.analytics, name='analytics'),
    path('shift_report/', views.shift_report, name='shift_report'),
]
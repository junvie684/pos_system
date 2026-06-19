from django.urls import path
from . import views

app_name = 'sales'
urlpatterns = [
    path('',                    views.dashboard,       name='dashboard'),
    path('new/',                views.create_sale,     name='create_sale'),
    path('history/',            views.sale_history,    name='sale_history'),
    path('pending/',             views.pending_sales,   name='pending_sales'),
    path('pending/<int:pk>/resume/', views.resume_sale, name='resume_sale'),
    path('pending/<int:pk>/delete/', views.delete_pending, name='delete_pending'),
    path('refund/<int:pk>/',    views.refund_sale,     name='refund_sale'),
    path('receipt/<int:sale_id>/', views.receipt, name='receipt'),
]
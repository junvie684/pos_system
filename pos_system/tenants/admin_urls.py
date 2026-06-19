from django.urls import path
from tenants.admin_views import (
    platform_login,
    platform_logout,
    dashboard,
    store_detail,
    edit_store,
    toggle_store,
    delete_store,
    add_store_user,
    edit_store_user,              # ← ADD THIS
    reset_store_user_password,    # ← ADD THIS
    remove_store_user,
    create_store,
)

app_name = 'platform_admin'

urlpatterns = [
    path('login/',                                             platform_login,    name='login'),
    path('logout/',                                            platform_logout,   name='logout'),
    path('',                                                   dashboard,         name='dashboard'),
    path('store/<uuid:tenant_id>/',                            store_detail,      name='store_detail'),
    path('store/<uuid:tenant_id>/edit/',                       edit_store,        name='edit_store'),
    path('store/<uuid:tenant_id>/toggle/',                     toggle_store,      name='toggle_store'),
    path('store/<uuid:tenant_id>/delete/',                     delete_store,      name='delete_store'),
    path('store/<uuid:tenant_id>/users/add/',                  add_store_user,    name='add_store_user'),
    path('store/<uuid:tenant_id>/users/<int:user_id>/edit/',  edit_store_user,   name='edit_store_user'),              # ← ADD THIS
    path('store/<uuid:tenant_id>/users/<int:user_id>/password/', reset_store_user_password, name='reset_store_user_password'),  # ← ADD THIS
    path('store/<uuid:tenant_id>/users/<int:user_id>/remove/', remove_store_user, name='remove_store_user'),
    path('stores/create/',                                     create_store,      name='create_store'),
]
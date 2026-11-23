from django.urls import path
from . import views

app_name = 'accounts'
urlpatterns = [
    path('login/',                          views.login_view,          name='login'),
    path('logout/',                         views.logout_view,         name='logout'),
    # User management (Admin only)
    path('users/',                          views.user_list,           name='user_list'),
    path('users/add/',                      views.user_add,            name='user_add'),
    path('users/<int:user_id>/edit/',       views.user_edit,           name='user_edit'),
    path('users/<int:user_id>/password/',   views.user_reset_password, name='user_reset_password'),
    path('users/<int:user_id>/remove/',     views.user_remove,         name='user_remove'),

]

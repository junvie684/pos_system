from django.urls import path
from . import views

app_name = 'accounts'
urlpatterns = [
    path('login/',                          views.login_view,          name='login'),
    path('logout/',                         views.logout_view,         name='logout'),
    # User management (Admin only)
    path('users/',                          views.user_list,           name='user_list'),

]

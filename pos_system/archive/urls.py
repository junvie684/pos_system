from django.urls import path

from . import views

app_name = 'archive'
urlpatterns = [
    path('<int:sale_id>/receipt/',    views.archived_receipt, name='archived_receipt'),
]

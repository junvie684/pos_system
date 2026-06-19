from django.db import models
from tenants.base_model import TenantModel

class Category(TenantModel):
    name = models.CharField(max_length=100)
    def __str__(self): return self.name

class Product(TenantModel):
    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    barcode = models.CharField(max_length=100, unique=True, blank=True, null=True)
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self): return self.name

    def is_in_stock(self): return self.stock > 0 and self.is_active
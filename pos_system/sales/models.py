from django.db import models
from django.contrib.auth.models import User
from products.models import Product
from customers.models import Customer
from tenants.base_model import TenantModel


class Sale(TenantModel):
    STATUS = [('pending','Pending'),('completed','Completed'),('refunded','Refunded')]
    PAYMENT_METHODS = [
        ('cash', 'Cash'),
        ('gcash', 'GCash'),
        ('maya', 'Maya'),
        ('grabpay', 'GrabPay'),
        ('bank_transfer', 'Bank Transfer'),
        ('credit_card', 'Credit Card'),
        ('debit_card', 'Debit Card'),
    ]
    customer         = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    cashier          = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    status           = models.CharField(max_length=20, choices=STATUS, default='completed')
    payment_method   = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='cash')
    reference_number = models.CharField(max_length=100, blank=True, null=True)
    cash_tendered    = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    change_given     = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)

    @property
    def total(self):
        return sum(item.subtotal for item in self.items.all())

    def __str__(self):
        return f"Sale #{self.pk}"


class SaleItem(TenantModel):
    sale       = models.ForeignKey(Sale, related_name='items', on_delete=models.CASCADE)
    product    = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity   = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def subtotal(self):
        return self.quantity * self.unit_price
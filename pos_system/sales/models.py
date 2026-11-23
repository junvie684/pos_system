from django.db import models
from django.db.models import Max
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
    refunded_by      = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                         related_name='refunds_processed')
    refunded_at      = models.DateTimeField(null=True, blank=True)
    # One per POS screen load; a resubmitted checkout (double-click, retry
    # after a dropped connection) carries the same key and maps to this sale.
    idempotency_key  = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    # Official receipt serial: one running number per store, given only when a
    # sale is completed (held sales don't use one up, so there are no gaps).
    or_number        = models.PositiveIntegerField(null=True, blank=True, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['tenant_id', 'or_number'], name='unique_or_number_per_store'),
        ]

    @property
    def or_display(self):
        return f"OR-{self.or_number:06d}" if self.or_number else ''

    def assign_or_number(self):
        """Give this sale the store's next OR number. Call inside the checkout
        transaction: the store row lock makes terminals take numbers one at a
        time, and a rolled-back sale gives its number back."""
        from tenants.models import Tenant
        if self.or_number:
            return
        store = Tenant.objects.select_for_update().filter(pk=self.tenant_id).first()
        # The store's counter survives archiving; the table max covers numbers
        # issued before the counter existed.
        in_table = (Sale.all_objects.filter(tenant_id=self.tenant_id)
                    .aggregate(m=Max('or_number'))['m']) or 0
        self.or_number = max(in_table, store.last_or_number if store else 0) + 1
        if store:
            Tenant.objects.filter(pk=store.pk).update(last_or_number=self.or_number)

    @property
    def total(self):
        return sum(item.subtotal for item in self.items.all())

    def __str__(self):
        return self.or_display or f"Sale #{self.pk}"


class SaleItem(TenantModel):
    sale       = models.ForeignKey(Sale, related_name='items', on_delete=models.CASCADE)
    product    = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity   = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def subtotal(self):
        return self.quantity * self.unit_price
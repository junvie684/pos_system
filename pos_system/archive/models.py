"""
Archived sales, stored in the separate pos_archive database.

A row here is a frozen copy of a paid sale (and its lines) that has been moved
out of the main database. It keeps the original sale ID and OR number, and
copies the names it pointed to (customer, cashier, product), because rows in
one database can't reference rows in another.

The attribute names mirror sales.Sale / sales.SaleItem closely enough that the
receipt and the report tables render either one.
"""
from decimal import Decimal

from django.db import models

from sales.models import Sale
from tenants.base_model import TenantModel


class Name(str):
    """A copied name that templates can use like the related object it replaced
    ({{ sale.customer }} and {{ sale.customer.name }} both work)."""

    @property
    def name(self):
        return str(self)


def _name(value):
    return Name(value) if value else None


class ArchivedSale(TenantModel):
    # Same ID as the sale had in the main database; not auto-assigned.
    id               = models.BigIntegerField(primary_key=True)
    or_number        = models.PositiveIntegerField(null=True, blank=True)
    status           = models.CharField(max_length=20, choices=Sale.STATUS)
    payment_method   = models.CharField(max_length=20, choices=Sale.PAYMENT_METHODS)
    reference_number = models.CharField(max_length=100, blank=True, null=True)
    cash_tendered    = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    change_given     = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total            = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    created_at       = models.DateTimeField()
    refunded_at      = models.DateTimeField(null=True, blank=True)

    customer_id      = models.BigIntegerField(null=True, blank=True)
    customer_name    = models.CharField(max_length=255, blank=True)
    cashier_id       = models.BigIntegerField(null=True, blank=True)
    cashier_name     = models.CharField(max_length=150, blank=True)
    refunded_by_name = models.CharField(max_length=150, blank=True)

    archived_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant_id', 'created_at'], name='arch_sale_store_date'),
            models.Index(fields=['tenant_id', 'or_number'], name='arch_sale_store_or'),
        ]

    # ── Same shape as sales.Sale for templates ──
    is_archived = True      # sales.Sale rows don't have this, so templates read it as false

    @property
    def or_display(self):
        return f"OR-{self.or_number:06d}" if self.or_number else ''

    @property
    def customer(self):
        return _name(self.customer_name)

    @property
    def cashier(self):
        return _name(self.cashier_name)

    @property
    def cashier_display(self):
        """The cashier's current full name (the copy only holds the username).
        Falls back to the copied username if the user is gone or has no name.
        The history view fills `_cashier_display` for a whole page in one query."""
        if not hasattr(self, '_cashier_display'):
            from django.contrib.auth.models import User
            user = User.objects.filter(pk=self.cashier_id).first() if self.cashier_id else None
            self._cashier_display = (user.get_full_name() if user else '') or self.cashier_name
        return self._cashier_display

    @property
    def refunded_by(self):
        return _name(self.refunded_by_name)

    @property
    def refunded_amount(self):
        """Money handed back (prefetch 'refunds' when listing)."""
        return sum((r.total for r in self.refunds.all()), start=Decimal('0.00'))

    @property
    def is_partly_refunded(self):
        return self.status == 'completed' and bool(self.refunded_amount)

    @property
    def kept_total(self):
        """What the customer paid, less everything refunded."""
        return self.total - self.refunded_amount

    def __str__(self):
        return self.or_display or f"Archived sale #{self.pk}"


class ArchivedSaleItem(TenantModel):
    sale            = models.ForeignKey(ArchivedSale, related_name='items', on_delete=models.CASCADE)
    product_id      = models.BigIntegerField(null=True, blank=True)
    product_name    = models.CharField(max_length=255)
    product_barcode = models.CharField(max_length=100, blank=True)
    quantity        = models.PositiveIntegerField()
    unit_price      = models.DecimalField(max_digits=10, decimal_places=2)
    unit_cost       = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  # see SaleItem

    @property
    def product(self):
        return _name(self.product_name)

    @property
    def subtotal(self):
        return self.quantity * self.unit_price


class ArchivedRefund(TenantModel):
    """Frozen copy of a sales.Refund, moved with its sale."""
    sale             = models.ForeignKey(ArchivedSale, related_name='refunds', on_delete=models.CASCADE)
    refunded_at      = models.DateTimeField(db_index=True)
    refunded_by_name = models.CharField(max_length=150, blank=True)
    total            = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        ordering = ['refunded_at', 'pk']

    # ── Same shape as sales.Refund for report tables ──
    is_archived = True

    @property
    def refund_time(self):
        return self.refunded_at

    @property
    def or_display(self):
        return self.sale.or_display

    @property
    def sale_id_display(self):
        return self.sale_id

    @property
    def sale_created_at(self):
        return self.sale.created_at

    @property
    def customer(self):
        return self.sale.customer

    @property
    def given_by(self):
        return _name(self.refunded_by_name) or self.sale.cashier

    def get_payment_method_display(self):
        return self.sale.get_payment_method_display()

    @property
    def items_text(self):
        return ', '.join(f'{i.product_name} ×{i.quantity}' for i in self.items.all())


class ArchivedRefundItem(TenantModel):
    refund       = models.ForeignKey(ArchivedRefund, related_name='items', on_delete=models.CASCADE)
    product_id   = models.BigIntegerField(null=True, blank=True)
    product_name = models.CharField(max_length=255)
    quantity     = models.PositiveIntegerField()
    unit_price   = models.DecimalField(max_digits=10, decimal_places=2)
    restocked    = models.BooleanField(default=True)

    @property
    def subtotal(self):
        return self.quantity * self.unit_price

from decimal import Decimal

from django.test import TestCase

from products.models import Product
from sales.models import Sale, SaleItem
from tenants.test_utils import (
    make_product, make_sale, make_tenant, make_user, pos_login, sale_post,
)


class SaleTestBase(TestCase):
    def setUp(self):
        self.tenant = make_tenant('store-a')
        self.cashier = make_user(self.tenant, 'cashier1')
        self.manager = make_user(self.tenant, 'manager1', role='manager')
        self.product = make_product(self.tenant, price='50.00', stock=10)

    def stock(self):
        return Product.all_objects.get(pk=self.product.pk).stock


# ─── C-3: server must price every line ──────────────────────────
class ServerSidePricingTests(SaleTestBase):
    def test_create_sale_ignores_client_unit_price(self):
        pos_login(self.client, self.cashier)
        self.client.post('/new/', sale_post([(self.product, 2, '0.01')], cash_tendered='100.00'))
        item = SaleItem.all_objects.get()
        self.assertEqual(item.unit_price, Decimal('50.00'))

    def test_resume_sale_ignores_client_unit_price(self):
        pending = make_sale(self.tenant, self.cashier, self.product, qty=1, status='pending')
        pos_login(self.client, self.cashier)
        self.client.post(
            f'/pending/{pending.pk}/resume/',
            sale_post([(self.product, 2, '0.01')], cash_tendered='100.00'),
        )
        pending.refresh_from_db()
        self.assertEqual(pending.status, 'completed')
        item = SaleItem.all_objects.get(sale=pending)
        self.assertEqual(item.unit_price, Decimal('50.00'))

    def test_resume_sale_rejects_inactive_product(self):
        pending = make_sale(self.tenant, self.cashier, self.product, qty=1, status='pending')
        Product.all_objects.filter(pk=self.product.pk).update(is_active=False)
        pos_login(self.client, self.cashier)
        self.client.post(
            f'/pending/{pending.pk}/resume/',
            sale_post([(self.product, 1, '50.00')], cash_tendered='50.00'),
        )
        pending.refresh_from_db()
        self.assertEqual(pending.status, 'pending')
        self.assertEqual(self.stock(), 10)


# ─── C-8: client cannot choose status / method / change ─────────
class CheckoutValidationTests(SaleTestBase):
    def setUp(self):
        super().setUp()
        pos_login(self.client, self.cashier)

    def test_status_outside_whitelist_creates_no_sale(self):
        self.client.post('/new/', sale_post([(self.product, 1, '50.00')], status='refunded'))
        self.assertFalse(Sale.all_objects.exists())
        self.assertEqual(self.stock(), 10)

    def test_unknown_payment_method_creates_no_sale(self):
        self.client.post('/new/', sale_post([(self.product, 1, '50.00')], payment_method='bitcoin'))
        self.assertFalse(Sale.all_objects.exists())

    def test_change_is_computed_by_server(self):
        self.client.post('/new/', sale_post(
            [(self.product, 1, '50.00')], cash_tendered='100.00', change_given='999.00'))
        sale = Sale.all_objects.get()
        self.assertEqual(sale.cash_tendered, Decimal('100.00'))
        self.assertEqual(sale.change_given, Decimal('50.00'))

    def test_blank_cash_tendered_means_exact_amount(self):
        self.client.post('/new/', sale_post([(self.product, 2, '50.00')]))
        sale = Sale.all_objects.get()
        self.assertEqual(sale.cash_tendered, Decimal('100.00'))
        self.assertEqual(sale.change_given, Decimal('0.00'))

    def test_cash_short_of_total_creates_no_sale(self):
        self.client.post('/new/', sale_post([(self.product, 2, '50.00')], cash_tendered='60.00'))
        self.assertFalse(Sale.all_objects.exists())
        self.assertEqual(self.stock(), 10)

    def test_ewallet_requires_reference_number(self):
        self.client.post('/new/', sale_post([(self.product, 1, '50.00')], payment_method='gcash'))
        self.assertFalse(Sale.all_objects.exists())

    def test_ewallet_sale_records_reference_and_no_cash(self):
        self.client.post('/new/', sale_post(
            [(self.product, 1, '50.00')], payment_method='gcash', reference_number='REF123',
            cash_tendered='50.00', change_given='5.00'))
        sale = Sale.all_objects.get()
        self.assertEqual(sale.reference_number, 'REF123')
        self.assertIsNone(sale.cash_tendered)
        self.assertIsNone(sale.change_given)

    def test_pending_sale_still_allowed(self):
        self.client.post('/new/', sale_post([(self.product, 1, '50.00')], status='pending'))
        sale = Sale.all_objects.get()
        self.assertEqual(sale.status, 'pending')
        self.assertEqual(self.stock(), 10)


# ─── C-6: refunds only for completed sales, recorded ────────────
class RefundTests(SaleTestBase):
    def test_refunding_pending_sale_is_rejected_and_stock_unchanged(self):
        pending = make_sale(self.tenant, self.cashier, self.product, qty=3, status='pending')
        pos_login(self.client, self.manager)
        self.client.post(f'/refund/{pending.pk}/')
        pending.refresh_from_db()
        self.assertEqual(pending.status, 'pending')
        self.assertEqual(self.stock(), 10)

    def test_refund_restores_stock_and_records_who_and_when(self):
        sale = make_sale(self.tenant, self.cashier, self.product, qty=3)
        pos_login(self.client, self.manager)
        self.client.post(f'/refund/{sale.pk}/')
        sale.refresh_from_db()
        self.assertEqual(sale.status, 'refunded')
        self.assertEqual(sale.refunded_by, self.manager)
        self.assertIsNotNone(sale.refunded_at)
        self.assertEqual(self.stock(), 13)

    def test_second_refund_does_not_restore_stock_again(self):
        sale = make_sale(self.tenant, self.cashier, self.product, qty=3)
        pos_login(self.client, self.manager)
        self.client.post(f'/refund/{sale.pk}/')
        self.client.post(f'/refund/{sale.pk}/')
        self.assertEqual(self.stock(), 13)

    def test_cashier_cannot_refund(self):
        sale = make_sale(self.tenant, self.cashier, self.product, qty=3)
        pos_login(self.client, self.cashier)
        self.client.post(f'/refund/{sale.pk}/')
        sale.refresh_from_db()
        self.assertEqual(sale.status, 'completed')

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


# ─── P1-1: the same checkout submitted twice records one sale ───
class DuplicateCheckoutTests(SaleTestBase):
    KEY = '6f1c7a52-0d4e-4c55-9a43-1f0a5d6f3b21'

    def setUp(self):
        super().setUp()
        pos_login(self.client, self.cashier)

    def post(self, key, ajax=True):
        data = sale_post([(self.product, 2, '50.00')], cash_tendered='100.00')
        if key is not None:
            data['idempotency_key'] = key
        headers = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'} if ajax else {}
        return self.client.post('/new/', data, **headers)

    def test_pos_screen_renders_a_fresh_key(self):
        first = self.client.get('/new/').context['idempotency_key']
        second = self.client.get('/new/').context['idempotency_key']
        self.assertTrue(first)
        self.assertNotEqual(first, second)

    def test_resubmitting_same_key_creates_one_sale_and_deducts_once(self):
        r1 = self.post(self.KEY)
        r2 = self.post(self.KEY)
        self.assertEqual(Sale.all_objects.count(), 1)
        self.assertEqual(self.stock(), 8)
        self.assertEqual(r1.json(), r2.json())
        self.assertEqual(r2.json()['sale_id'], Sale.all_objects.get().pk)

    def test_non_ajax_retry_with_same_key_goes_to_existing_receipt(self):
        self.post(self.KEY)
        resp = self.post(self.KEY, ajax=False)
        sale = Sale.all_objects.get()
        self.assertRedirects(resp, f'/receipt/{sale.pk}/', fetch_redirect_response=False)

    def test_different_keys_create_separate_sales(self):
        self.post(self.KEY)
        self.post('0b8c4c4e-31a5-4c8e-8d0e-6b2a3f7d9e10')
        self.assertEqual(Sale.all_objects.count(), 2)
        self.assertEqual(self.stock(), 6)

    def test_retried_resume_completion_returns_the_same_sale(self):
        pending = make_sale(self.tenant, self.cashier, self.product, qty=1, status='pending')
        data = sale_post([(self.product, 2, '50.00')], cash_tendered='100.00')
        data['idempotency_key'] = self.KEY
        ajax = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        self.client.post(f'/pending/{pending.pk}/resume/', data, **ajax)
        retry = self.client.post(f'/pending/{pending.pk}/resume/', data, **ajax)
        self.assertEqual(retry.json(), {'success': True, 'sale_id': pending.pk})
        self.assertEqual(self.stock(), 8)

    def test_missing_or_malformed_key_still_checks_out(self):
        self.post(None)
        self.post('not-a-uuid')
        self.assertEqual(Sale.all_objects.count(), 2)


# ─── P1-6: product names can't break out of the script block ────
class PreservedCartEscapingTests(SaleTestBase):
    def test_product_name_with_script_tag_is_not_rendered_raw(self):
        evil = make_product(self.tenant, name='</script><script>alert(1)</script>', stock=0)
        pos_login(self.client, self.cashier)
        # Out of stock -> cart is preserved in the session and re-rendered.
        self.client.post('/new/', sale_post([(evil, 1, '50.00')]))
        resp = self.client.get('/new/')
        self.assertNotIn(b'</script><script>alert(1)', resp.content)
        self.assertIn('preserved-cart', resp.content.decode())


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

from decimal import Decimal

from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from products.models import Product
from sales.models import Sale, SaleItem
from tenants.middleware import tenant_context
from tenants.test_utils import (
    make_product, make_refund, make_sale, make_tenant, make_user, pos_login, sale_post,
)


class SaleTestBase(TestCase):
    def setUp(self):
        self.tenant = make_tenant('store-a')
        self.cashier = make_user(self.tenant, 'cashier1')
        self.manager = make_user(self.tenant, 'manager1', role='manager')
        self.product = make_product(self.tenant, price='50.00', stock=10)

    def stock(self):
        return Product.all_objects.get(pk=self.product.pk).stock


class CashierTemplateContractTests(SaleTestBase):
    def setUp(self):
        super().setUp()
        self.pending = make_sale(self.tenant, self.cashier, self.product, status='pending')
        self.completed = make_sale(self.tenant, self.cashier, self.product)

    def test_register_exposes_catalog_and_current_sale_regions(self):
        pos_login(self.client, self.cashier)

        response = self.client.get('/new/')

        self.assertContains(response, 'data-cashier-workspace="register"')
        self.assertContains(response, 'data-register-toolbar="catalog-controls"')
        self.assertContains(response, 'data-register-region="catalog"')
        self.assertContains(response, 'data-register-region="current-sale"')
        self.assertContains(response, 'aria-label="Checkout workspace"')

    def test_register_exposes_safe_initial_action_and_live_status_states(self):
        pos_login(self.client, self.cashier)

        response = self.client.get('/new/')

        self.assertContains(response, 'id="cart-status"')
        self.assertContains(response, 'id="clear-cart-btn"')
        self.assertContains(response, 'id="hold-btn"')
        self.assertContains(response, 'id="complete-btn"')
        self.assertContains(response, 'aria-label="Sale actions"')
        # The total, and the hint saying why the button waits for the cash received
        self.assertContains(response, 'aria-describedby="cart-total cash-needed"')
        self.assertContains(response, 'id="cash-needed"')

    def test_held_sale_screens_expose_cashier_flow_landmarks(self):
        pos_login(self.client, self.cashier)

        listing = self.client.get('/pending/')
        confirmation = self.client.get(f'/pending/{self.pending.pk}/delete/')

        self.assertContains(listing, 'data-cashier-screen="held-sales"')
        self.assertContains(listing, 'id="held-sales-note"')
        self.assertContains(listing, 'aria-hidden="true"')
        self.assertContains(confirmation, 'data-cashier-screen="delete-held-sale"')
        self.assertContains(confirmation, 'aria-labelledby="delete-held-title"')

    def test_receipt_and_refund_expose_transaction_state_landmarks(self):
        pos_login(self.client, self.cashier)
        receipt = self.client.get(f'/receipt/{self.completed.pk}/')

        self.client.post('/accounts/logout/')
        pos_login(self.client, self.manager)
        refund = self.client.get(f'/refund/{self.completed.pk}/')

        self.assertContains(receipt, 'data-receipt-state="completed"')
        self.assertContains(receipt, 'class="receipt-paper"')
        self.assertContains(refund, 'data-cashier-screen="refund-confirmation"')
        self.assertContains(refund, 'aria-labelledby="refund-title"')
        self.assertContains(refund, 'aria-describedby="refund-warning"')


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


# ─── Fix 1: POS can find any product, not just the 24 shown ─────
class ProductLookupApiTests(SaleTestBase):
    URL = '/api/products/'

    def setUp(self):
        super().setUp()
        # 30 extra products: more than the 24 the POS grid shows
        for i in range(30):
            make_product(self.tenant, name=f'Item {i:02d}', price='10.00', stock=5)
        self.rare = make_product(self.tenant, name='Rare Widget', price='99.00', stock=3)
        Product.all_objects.filter(pk=self.rare.pk).update(barcode='4800000000017')

    def test_requires_pos_login(self):
        resp = self.client.get(self.URL, {'q': 'Rare'})
        self.assertNotEqual(resp.status_code, 200)

    def test_exact_barcode_finds_product_outside_the_grid(self):
        pos_login(self.client, self.cashier)
        data = self.client.get(self.URL, {'barcode': '4800000000017'}).json()
        self.assertEqual([p['id'] for p in data['products']], [self.rare.pk])
        self.assertEqual(data['products'][0]['price'], '99.00')

    def test_barcode_must_match_exactly(self):
        pos_login(self.client, self.cashier)
        data = self.client.get(self.URL, {'barcode': '48000'}).json()
        self.assertEqual(data['products'], [])

    def test_search_by_name_is_capped(self):
        pos_login(self.client, self.cashier)
        data = self.client.get(self.URL, {'q': 'item'}).json()
        self.assertEqual(len(data['products']), 20)
        data = self.client.get(self.URL, {'q': 'rare wid'}).json()
        self.assertEqual([p['id'] for p in data['products']], [self.rare.pk])

    def test_inactive_and_other_store_products_are_hidden(self):
        Product.all_objects.filter(pk=self.rare.pk).update(is_active=False)
        other = make_tenant('store-b')
        foreign = make_product(other, name='Rare Foreign')
        Product.all_objects.filter(pk=foreign.pk).update(barcode='4800000000024')
        pos_login(self.client, self.cashier)
        self.assertEqual(self.client.get(self.URL, {'q': 'rare'}).json()['products'], [])
        self.assertEqual(self.client.get(self.URL, {'barcode': '4800000000024'}).json()['products'], [])

    def test_empty_query_returns_nothing(self):
        pos_login(self.client, self.cashier)
        self.assertEqual(self.client.get(self.URL).json()['products'], [])

    def test_pos_screen_points_at_the_lookup_api(self):
        pos_login(self.client, self.cashier)
        self.assertContains(self.client.get('/new/'), self.URL)


# ─── Fix 3: resumed cart shows what will actually be charged ────
class ResumeShowsCurrentPriceTests(SaleTestBase):
    def test_resumed_cart_uses_current_price_and_flags_change(self):
        pending = make_sale(self.tenant, self.cashier, self.product, qty=2, status='pending')
        Product.all_objects.filter(pk=self.product.pk).update(price=Decimal('65.00'))
        pos_login(self.client, self.cashier)
        cart = self.client.get(f'/pending/{pending.pk}/resume/').context['pending_cart']
        self.assertEqual(cart, [{
            'product_id': str(self.product.pk), 'name': 'Soap', 'unit_price': 65.0,
            'quantity': 2, 'stock': 10, 'price_changed': True,
        }])

    def test_inactive_product_is_left_out_of_resumed_cart(self):
        pending = make_sale(self.tenant, self.cashier, self.product, qty=1, status='pending')
        Product.all_objects.filter(pk=self.product.pk).update(is_active=False)
        pos_login(self.client, self.cashier)
        ctx = self.client.get(f'/pending/{pending.pk}/resume/').context
        self.assertEqual(ctx['pending_cart'], [])
        self.assertEqual(ctx['pending_removed'], ['Soap'])


# ─── Fix 8: duplicate lines are checked as one quantity ─────────
class DuplicateLineTests(SaleTestBase):
    def setUp(self):
        super().setUp()
        Product.all_objects.filter(pk=self.product.pk).update(stock=5)
        pos_login(self.client, self.cashier)

    def test_split_lines_over_stock_get_the_stock_message(self):
        resp = self.client.post('/new/', sale_post(
            [(self.product, 3, '50.00'), (self.product, 3, '50.00')], cash_tendered='300.00'), follow=True)
        self.assertFalse(Sale.all_objects.exists())
        self.assertEqual(self.stock(), 5)
        self.assertContains(resp, 'requested 6, only 5 in stock')

    def test_split_lines_within_stock_become_one_line(self):
        self.client.post('/new/', sale_post(
            [(self.product, 2, '50.00'), (self.product, 2, '50.00')], cash_tendered='200.00'))
        item = SaleItem.all_objects.get()
        self.assertEqual(item.quantity, 4)
        self.assertEqual(self.stock(), 1)


# ─── C-6: refunds only for completed sales, recorded ────────────
class RefundTests(SaleTestBase):
    @staticmethod
    def refund_all(sale):
        """Form data refunding every item of a sale, back into stock."""
        return {k: v for item in SaleItem.all_objects.filter(sale=sale)
                for k, v in ((f'qty_{item.pk}', str(item.quantity)), (f'restock_{item.pk}', 'on'))}

    def test_refunding_pending_sale_is_rejected_and_stock_unchanged(self):
        pending = make_sale(self.tenant, self.cashier, self.product, qty=3, status='pending')
        pos_login(self.client, self.manager)
        self.client.post(f'/refund/{pending.pk}/', self.refund_all(pending))
        pending.refresh_from_db()
        self.assertEqual(pending.status, 'pending')
        self.assertEqual(self.stock(), 10)

    def test_refund_restores_stock_and_records_who_and_when(self):
        sale = make_sale(self.tenant, self.cashier, self.product, qty=3)
        pos_login(self.client, self.manager)
        self.client.post(f'/refund/{sale.pk}/', self.refund_all(sale))
        sale.refresh_from_db()
        self.assertEqual(sale.status, 'refunded')
        self.assertEqual(sale.refunded_by, self.manager)
        self.assertIsNotNone(sale.refunded_at)
        self.assertEqual(self.stock(), 13)

    def test_second_refund_does_not_restore_stock_again(self):
        sale = make_sale(self.tenant, self.cashier, self.product, qty=3)
        pos_login(self.client, self.manager)
        self.client.post(f'/refund/{sale.pk}/', self.refund_all(sale))
        self.client.post(f'/refund/{sale.pk}/', self.refund_all(sale))
        self.assertEqual(self.stock(), 13)

    def test_cashier_cannot_refund(self):
        sale = make_sale(self.tenant, self.cashier, self.product, qty=3)
        pos_login(self.client, self.cashier)
        self.client.post(f'/refund/{sale.pk}/', self.refund_all(sale))
        sale.refresh_from_db()
        self.assertEqual(sale.status, 'completed')


class ItemRefundTests(SaleTestBase):
    """Refunding some of a sale's items, choosing what goes back to stock."""
    databases = {'default', 'archive'}   # reports and history also read the archive database

    def setUp(self):
        super().setUp()
        self.rice = make_product(self.tenant, name='Rice', price='20.00', stock=10)
        self.sale = make_sale(self.tenant, self.cashier, self.product, qty=3)      # 3 x 50
        self.rice_line = SaleItem.all_objects.create(
            tenant_id=self.tenant.id, sale=self.sale, product=self.rice, quantity=2, unit_price=Decimal('20.00'))
        self.soap_line = SaleItem.all_objects.get(sale=self.sale, product=self.product)
        pos_login(self.client, self.manager)

    def post(self, **qty):
        data = {}
        for line, (n, restock) in qty.items():
            item = getattr(self, f'{line}_line')
            data[f'qty_{item.pk}'] = str(n)
            if restock:
                data[f'restock_{item.pk}'] = 'on'
        return self.client.post(f'/refund/{self.sale.pk}/', data)

    def test_refund_page_lists_each_item(self):
        page = self.client.get(f'/refund/{self.sale.pk}/')
        self.assertContains(page, f'name="qty_{self.soap_line.pk}"')
        self.assertContains(page, f'name="restock_{self.rice_line.pk}"')

    def test_part_refund_keeps_sale_completed_and_restocks_only_ticked_items(self):
        from sales.models import Refund
        self.post(soap=(1, True), rice=(2, False))
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, 'completed')
        self.assertEqual(self.stock(), 11)                                            # soap restocked
        self.assertEqual(Product.all_objects.get(pk=self.rice.pk).stock, 10)          # rice not
        with tenant_context(self.tenant.id):
            refund = Refund.objects.get(sale=self.sale)
            self.assertEqual((refund.total, refund.refunded_by), (Decimal('90.00'), self.manager))
            self.assertEqual(self.sale.refunded_amount, Decimal('90.00'))
            self.assertEqual(self.sale.kept_total, Decimal('100.00'))

    def test_second_refund_of_the_rest_marks_sale_refunded(self):
        self.post(soap=(1, True))
        self.post(soap=(2, True), rice=(2, True))
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, 'refunded')
        self.assertEqual(self.sale.refunded_by, self.manager)
        with tenant_context(self.tenant.id):
            self.assertEqual(self.sale.refunds.count(), 2)
        self.assertEqual(self.stock(), 13)

    def test_cannot_refund_more_than_is_left(self):
        from sales.models import Refund
        self.post(soap=(2, True))
        resp = self.post(soap=(2, True))
        self.assertRedirects(resp, f'/refund/{self.sale.pk}/', fetch_redirect_response=False)
        self.assertEqual(Refund.all_objects.count(), 1)
        self.assertEqual(self.stock(), 12)

    def test_nothing_picked_or_bad_quantity_is_rejected(self):
        from sales.models import Refund
        self.post(soap=(0, True))
        self.post(soap=(-1, True))
        self.client.post(f'/refund/{self.sale.pk}/', {f'qty_{self.soap_line.pk}': 'two'})
        self.assertFalse(Refund.all_objects.exists())

    def test_part_refund_counts_on_its_own_day_in_reports(self):
        self.post(rice=(1, True))
        today = timezone.localdate().isoformat()
        ctx = self.client.get('/reports/', {'day': today}).context
        self.assertEqual(Decimal(str(ctx['refunds_total'])), Decimal('20.00'))
        self.assertEqual(Decimal(str(ctx['gross_sales'])), Decimal('190.00'))
        shift = self.client.get('/reports/shift_report/', {'day': today}).context
        self.assertEqual(Decimal(str(shift['cash_refunds'])), Decimal('20.00'))
        tile = self.client.get('/').context['tiles'][0]
        self.assertEqual((tile['refunds'], tile['refund_cost']), (1, Decimal('20.00')))
        rice = next(r for r in self.client.get('/').context['rows'] if r['name'] == 'Rice')
        self.assertEqual((rice['refund_units'], rice['refund_cost']), (1, Decimal('20.00')))

    def test_history_shows_partly_refunded(self):
        self.post(rice=(1, True))
        page = self.client.get('/history/')
        self.assertContains(page, 'Partly refunded')
        self.assertEqual(page.context['filtered_total'], Decimal('170.00'))
        receipt = self.client.get(f'/receipt/{self.sale.pk}/')
        self.assertContains(receipt, 'Kept after refunds')


class OrNumberTests(SaleTestBase):
    databases = {'default', 'archive'}   # sales history also reads the archive database

    def setUp(self):
        super().setUp()
        pos_login(self.client, self.cashier)

    def checkout(self, status='completed'):
        self.client.post('/new/', sale_post([(self.product, 1, '50.00')], status=status, cash_tendered='50.00'))
        return Sale.all_objects.latest('pk')

    def test_completed_sales_get_running_or_numbers(self):
        first, second = self.checkout(), self.checkout()
        self.assertEqual((first.or_number, second.or_number), (1, 2))
        self.assertEqual(second.or_display, 'OR-000002')

    def test_held_sale_gets_no_number_until_completed(self):
        held = self.checkout(status='pending')
        self.assertIsNone(held.or_number)
        done = self.checkout()
        self.assertEqual(done.or_number, 1)  # the held sale didn't use one up
        self.client.post(f'/pending/{held.pk}/resume/',
                         sale_post([(self.product, 1, '50.00')], cash_tendered='50.00'))
        held.refresh_from_db()
        self.assertEqual(held.or_number, 2)

    def test_each_store_counts_from_one(self):
        self.checkout()
        other = make_tenant('store-b')
        cashier_b = make_user(other, 'cashier-b')
        product_b = make_product(other, price='20.00', stock=5)
        client_b = self.client_class()
        pos_login(client_b, cashier_b)
        client_b.post('/new/', sale_post([(product_b, 1, '20.00')], cash_tendered='20.00'))
        self.assertEqual(Sale.all_objects.filter(tenant_id=other.id).get().or_number, 1)

    def test_history_and_receipt_show_cashier_full_name(self):
        self.cashier.first_name, self.cashier.last_name = 'Maria', 'Santos'
        self.cashier.save()
        sale = self.checkout()
        receipt = self.client.get(f'/receipt/{sale.pk}/')
        self.assertContains(receipt, 'Maria Santos')
        self.client.post('/accounts/logout/')
        pos_login(self.client, self.manager)
        resp = self.client.get('/history/', {'q': 'maria santos'})
        self.assertEqual([s.pk for s in resp.context['sales']], [sale.pk])
        self.assertContains(resp, 'Maria Santos')

    def test_cashier_without_a_name_shows_username(self):
        sale = self.checkout()
        self.assertContains(self.client.get(f'/receipt/{sale.pk}/'), 'cashier1')

    def test_receipt_and_history_show_or_number(self):
        sale = self.checkout()
        self.assertContains(self.client.get(f'/receipt/{sale.pk}/'), 'OR-000001')
        self.client.post('/accounts/logout/')
        pos_login(self.client, self.manager)
        resp = self.client.get('/history/', {'q': 'OR-000001'})
        self.assertEqual([s.pk for s in resp.context['sales']], [sale.pk])


class PnlTests(SaleTestBase):
    databases = {'default', 'archive'}   # the P&L also reads the archive database

    def test_pnl_shows_monthly_sales_refunds_and_net(self):
        from django.utils import timezone
        make_sale(self.tenant, self.cashier, self.product, qty=3)            # 150.00
        refunded = make_sale(self.tenant, self.cashier, self.product, qty=1)  # 50.00
        make_refund(refunded)
        pos_login(self.client, self.manager)
        resp = self.client.get('/pnl/')
        self.assertEqual(resp.status_code, 200)
        rows = {r['key']: r for r in resp.context['rows']}
        self.assertEqual(len(resp.context['columns']), 12)
        self.assertEqual(rows['sales']['values'][0], Decimal('200.00'))
        self.assertEqual(rows['units']['values'][0], 4)
        self.assertEqual(rows['txns']['values'][0], 2)
        self.assertEqual(rows['refunds']['values'][0], 1)
        self.assertEqual(rows['refund_cost']['values'][0], Decimal('-50.00'))
        self.assertEqual(rows['net']['total'], Decimal('150.00'))
        self.assertEqual(rows['refund_rate']['values'][0], 50)
        self.assertEqual(rows['sales']['children'][0]['label'], 'Cash')
        self.assertEqual(rows['avg']['values'][1], None)
        self.assertContains(resp, '−₱50.00')

    def test_pnl_csv_download(self):
        make_sale(self.tenant, self.cashier, self.product, qty=2)
        pos_login(self.client, self.manager)
        resp = self.client.get('/pnl/?months=3&format=csv')
        self.assertEqual(resp['Content-Type'], 'text/csv; charset=utf-8')
        body = resp.content.decode('utf-8-sig')
        self.assertIn('Parameter,', body)
        self.assertIn('₱100.00', body)
        self.assertEqual(body.splitlines()[0].count(','), 4)

    def test_pnl_needs_reports_access(self):
        user = make_user(self.tenant, 'noreports', can_access_reports=False, can_access_dashboard=True)
        pos_login(self.client, user)
        resp = self.client.get('/pnl/')
        self.assertRedirects(resp, '/', fetch_redirect_response=False)
        resp = self.client.get('/')
        self.assertNotContains(resp, 'href="/pnl/"')

    def test_dashboard_has_pnl_tab_for_reports_users(self):
        pos_login(self.client, self.manager)
        resp = self.client.get('/')
        self.assertContains(resp, 'href="/pnl/"')


class DashboardTilesTests(SaleTestBase):
    databases = {'default', 'archive'}   # the tiles also read the archive database

    def setUp(self):
        super().setUp()
        make_sale(self.tenant, self.cashier, self.product, qty=2)   # 100.00 today
        self.cashier.profile.can_access_dashboard = True   # cashiers need the switch for the dashboard
        self.cashier.profile.save()
        pos_login(self.client, self.cashier)

    def test_default_tiles_and_today_products(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        titles = [t['title'] for t in resp.context['tiles']]
        self.assertEqual(titles, ['Today', 'Yesterday', 'Month to date', 'This month (forecast)', 'Last month'])
        today = resp.context['tiles'][0]
        self.assertEqual((today['sales'], today['txns'], today['units']), (Decimal('100.00'), 1, 2))
        self.assertEqual(resp.context['groups'][0]['items'][0]['units'], 2)
        self.assertContains(resp, 'Show details')

    def test_every_preset_renders(self):
        from reports.tiles import PRESETS
        for key in PRESETS:
            with self.subTest(key):
                resp = self.client.get('/', {'preset': key, 'tile': 1, 'view': 'items'})
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.context['preset'], key)

    def test_custom_range_and_bad_input_fall_back(self):
        resp = self.client.get('/', {'preset': 'custom', 'from': '2020-01-01', 'to': '2099-01-01'})
        self.assertEqual([t['title'] for t in resp.context['tiles']], ['Custom range'])
        self.assertEqual(resp.context['tiles'][0]['sales'], Decimal('100.00'))
        resp = self.client.get('/', {'preset': 'custom', 'from': 'nope', 'tile': '99'})
        self.assertEqual(resp.context['preset'], 'default')
        self.assertEqual(resp.context['selected'], 0)

    def test_order_items_and_flat_products(self):
        resp = self.client.get('/', {'view': 'items'})
        self.assertEqual(resp.context['line_total'], 1)
        resp = self.client.get('/', {'group': 'none'})
        self.assertIsNone(resp.context['groups'])
        self.assertEqual(len(resp.context['rows']), 1)

    def test_refund_counts_on_refund_day(self):
        from django.utils import timezone
        sale = make_sale(self.tenant, self.cashier, self.product, qty=1)
        make_refund(sale)
        tile = self.client.get('/').context['tiles'][0]
        self.assertEqual((tile['refunds'], tile['refund_cost'], tile['net']),
                         (1, Decimal('50.00'), Decimal('100.00')))


class DashboardChartsTests(SaleTestBase):
    databases = {'default', 'archive'}   # the charts also read the archive database

    def setUp(self):
        super().setUp()
        make_sale(self.tenant, self.cashier, self.product, qty=2)   # 100.00 today
        self.cashier.profile.can_access_dashboard = True   # cashiers need the switch for the dashboard
        self.cashier.profile.save()
        pos_login(self.client, self.cashier)

    def test_default_chart_by_month_with_breakdowns(self):
        resp = self.client.get('/charts/')
        self.assertEqual(resp.status_code, 200)
        ctx = resp.context
        self.assertEqual((ctx['step'], len(ctx['series']['buckets'])), ('month', 12))
        last = ctx['series']['buckets'][-1]
        self.assertTrue(last['is_current'])
        self.assertEqual(last['value'], Decimal('100.00'))
        self.assertEqual(ctx['payments'][0]['label'], 'Cash')
        self.assertEqual(ctx['top_products'][0]['value'], Decimal('100.00'))
        self.assertEqual(ctx['cashiers'][0]['orders'], 1)
        self.assertEqual(sum(1 for h in ctx['hours'] if h['value']), 1)
        self.assertEqual(len(ctx['weekdays']), 7)

    def test_ranges_and_metrics(self):
        for rng, step, n in (('3m', 'week', 13), ('30d', 'day', 30)):
            for metric in ('sales', 'net', 'txns', 'units', 'refunds', 'avg'):
                with self.subTest(rng=rng, metric=metric):
                    ctx = self.client.get('/charts/', {'range': rng, 'metric': metric}).context
                    self.assertEqual((ctx['step'], len(ctx['series']['buckets'])), (step, n))
        ctx = self.client.get('/charts/', {'range': '30d', 'metric': 'txns'}).context
        self.assertEqual(ctx['series']['buckets'][-1]['value'], 1)

    def test_custom_range_picks_step_and_bad_input_falls_back(self):
        from django.utils import timezone
        today = timezone.localdate()
        ctx = self.client.get('/charts/', {'range': 'custom', 'from': (today.replace(day=1)).isoformat(),
                                           'to': today.isoformat()}).context
        self.assertEqual(ctx['step'], 'day')
        ctx = self.client.get('/charts/', {'range': 'custom', 'from': 'x', 'metric': 'bogus'}).context
        self.assertEqual((ctx['range_key'], ctx['metric']), ('12m', 'sales'))

    def test_tabs_link_to_chart(self):
        self.assertContains(self.client.get('/'), 'href="/charts/"')


class NiceTicksTests(TestCase):
    def test_ticks_cover_the_top_with_round_steps(self):
        from reports.charts import nice_ticks
        self.assertEqual(nice_ticks(3705), [0, 1000, 2000, 3000, 4000])
        self.assertEqual(nice_ticks(4), [0, 1, 2, 3, 4])
        self.assertEqual(nice_ticks(0), [0, 1])


class RefundBackfillMigrationTests(TransactionTestCase):
    """Sales refunded before item refunds existed become one full refund each."""
    databases = {'default', 'archive'}

    def test_old_refunded_sale_becomes_a_full_refund(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        from datetime import timedelta
        from uuid import uuid4

        executor = MigrationExecutor(connection)
        before = ('sales', '0007_sale_or_number')
        executor.migrate([before])
        others = [n for n in executor.loader.graph.leaf_nodes() if n[0] not in ('sales', 'archive')]
        old = executor.loader.project_state([before, *others]).apps
        OldSale, OldItem = old.get_model('sales', 'Sale'), old.get_model('sales', 'SaleItem')
        OldProduct = old.get_model('products', 'Product')
        tenant = uuid4()
        product = OldProduct.objects.create(tenant_id=tenant, name='Soap', price=Decimal('50.00'), stock=1)
        sold = timezone.now() - timedelta(days=3)
        dated = OldSale.objects.create(tenant_id=tenant, status='refunded', refunded_at=sold + timedelta(days=1))
        legacy = OldSale.objects.create(tenant_id=tenant, status='refunded')       # no refund date
        OldSale.objects.filter(pk=legacy.pk).update(created_at=sold)
        kept = OldSale.objects.create(tenant_id=tenant, status='completed')
        for sale in (dated, legacy, kept):
            OldItem.objects.create(tenant_id=tenant, sale=sale, product=product, quantity=2, unit_price=Decimal('50.00'))

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

        from sales.models import Refund, RefundItem
        self.assertEqual(Refund.all_objects.count(), 2)
        self.assertEqual(Refund.all_objects.get(sale_id=dated.pk).refunded_at, dated.refunded_at)
        self.assertEqual(Refund.all_objects.get(sale_id=legacy.pk).refunded_at, sold)
        line = RefundItem.all_objects.get(refund__sale_id=dated.pk)
        self.assertEqual((line.quantity, line.unit_price, line.restocked), (2, Decimal('50.00'), True))
        self.assertFalse(Refund.all_objects.filter(sale_id=kept.pk).exists())


class DashboardPdfExportTests(SaleTestBase):
    databases = {'default', 'archive'}

    def test_every_tab_has_pdf_export_with_print_header(self):
        pos_login(self.client, self.manager)
        for url, title in (('/', 'Tiles'), ('/charts/', 'Chart'), ('/pnl/', 'P&amp;L')):
            with self.subTest(url):
                page = self.client.get(url)
                self.assertContains(page, 'onclick="exportPdf()"')
                self.assertContains(page, f'Dashboard · {title}')
                self.assertContains(page, 'class="print-head"')
                self.assertIn(timezone.localdate().isoformat(), page.context['print_filename_json'])
                self.assertNotContains(page, 'PDF export for the Dashboard')   # comment stays hidden

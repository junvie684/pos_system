from decimal import Decimal

from django.test import TestCase

from sales.models import Sale
from tenants.test_utils import make_product, make_sale, make_tenant, make_user, pos_login



# ─── P1-2: drawer reconciliation counts only cash ───────────────
class ShiftReportCashSplitTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant('store-a')
        self.manager = make_user(self.tenant, 'manager1', role='manager')
        self.cashier = make_user(self.tenant, 'cashier1')
        product = make_product(self.tenant, price='50.00', stock=100)

        make_sale(self.tenant, self.cashier, product, qty=2)            # cash ₱100
        gcash = make_sale(self.tenant, self.cashier, product, qty=1)    # GCash ₱50
        card = make_sale(self.tenant, self.cashier, product, qty=3)     # card ₱150
        Sale.all_objects.filter(pk=gcash.pk).update(payment_method='gcash')
        Sale.all_objects.filter(pk=card.pk).update(payment_method='credit_card')

        pos_login(self.client, self.manager)
        self.ctx = self.client.get(
            '/reports/shift_report/', {'starting_cash': '500', 'less_collection': '40'}
        ).context

    def test_total_sales_includes_every_payment_method(self):
        self.assertEqual(Decimal(str(self.ctx['total_sales'])), Decimal('300'))

    def test_cash_sales_counts_only_cash(self):
        self.assertEqual(Decimal(str(self.ctx['cash_sales'])), Decimal('100'))

    def test_non_cash_sales_are_reported_separately(self):
        self.assertEqual(Decimal(str(self.ctx['non_cash_sales'])), Decimal('200'))
        breakdown = {row['label']: Decimal(str(row['amount'])) for row in self.ctx['non_cash_breakdown']}
        self.assertEqual(breakdown, {'GCash': Decimal('50'), 'Credit Card': Decimal('150')})

    def test_expected_drawer_is_starting_cash_plus_cash_sales_minus_collection(self):
        self.assertEqual(Decimal(str(self.ctx['total_gross'])), Decimal('600'))   # 500 + 100
        self.assertEqual(Decimal(str(self.ctx['net_amount'])), Decimal('560'))    # 600 - 40

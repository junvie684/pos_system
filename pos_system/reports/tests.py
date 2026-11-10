from datetime import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from sales.models import Sale
from tenants.test_utils import make_product, make_sale, make_tenant, make_user, pos_login


def at(day, hour=10):
    return timezone.make_aware(datetime(2026, 3, day, hour, 0))


def dec(value):
    return Decimal(str(value))


# ─── Refunds count on the day the money went back ───────────────
class RefundLedgerTests(TestCase):
    """
    Mar 10: sale A (cash ₱100) and sale D (GCash ₱50) are made.
    Mar 11: manager refunds A and D; sale B (cash ₱50) is made.
    Mar 9:  legacy sale C (cash ₱150) refunded before refund dates were recorded.
    """

    def setUp(self):
        self.tenant = make_tenant('store-a')
        self.manager = make_user(self.tenant, 'manager1', role='manager')
        self.cashier = make_user(self.tenant, 'cashier1')
        product = make_product(self.tenant, price='50.00', stock=100)

        a = make_sale(self.tenant, self.cashier, product, qty=2)
        d = make_sale(self.tenant, self.cashier, product, qty=1)
        b = make_sale(self.tenant, self.cashier, product, qty=1)
        c = make_sale(self.tenant, self.cashier, product, qty=3)
        Sale.all_objects.filter(pk=a.pk).update(created_at=at(10), status='refunded',
                                                refunded_at=at(11, 15), refunded_by=self.manager)
        Sale.all_objects.filter(pk=d.pk).update(created_at=at(10, 11), status='refunded', payment_method='gcash',
                                                reference_number='R1', refunded_at=at(11, 16),
                                                refunded_by=self.manager)
        Sale.all_objects.filter(pk=b.pk).update(created_at=at(11))
        Sale.all_objects.filter(pk=c.pk).update(created_at=at(9), status='refunded')  # refunded_at NULL

        pos_login(self.client, self.manager)

    def daily(self, day):
        return self.client.get('/reports/', {'day': f'2026-03-{day:02d}'}).context

    def shift(self, day, **params):
        return self.client.get('/reports/shift_report/',
                               {'day': f'2026-03-{day:02d}', 'starting_cash': '500', **params}).context

    # Daily report
    def test_refunded_sale_still_counts_on_the_day_it_was_made(self):
        ctx = self.daily(10)
        self.assertEqual(dec(ctx['gross_sales']), Decimal('150'))
        self.assertEqual(dec(ctx['refunds_total']), Decimal('0'))
        self.assertEqual(dec(ctx['total']), Decimal('150'))

    def test_refund_is_deducted_on_the_day_it_was_given(self):
        ctx = self.daily(11)
        self.assertEqual(dec(ctx['gross_sales']), Decimal('50'))
        self.assertEqual(dec(ctx['refunds_total']), Decimal('150'))
        self.assertEqual(dec(ctx['total']), Decimal('-100'))

    def test_legacy_refund_without_date_nets_to_zero_on_its_sale_day(self):
        ctx = self.daily(9)
        self.assertEqual(dec(ctx['gross_sales']), Decimal('150'))
        self.assertEqual(dec(ctx['refunds_total']), Decimal('150'))
        self.assertEqual(dec(ctx['total']), Decimal('0'))

    def test_transaction_count_is_not_limited_to_one_page(self):
        self.assertEqual(self.daily(10)['transaction_count'], 2)

    # Monthly report
    def test_monthly_report_nets_refunds(self):
        ctx = self.client.get('/reports/monthly/', {'month': 3, 'year': 2026}).context
        self.assertEqual(dec(ctx['gross_sales']), Decimal('350'))   # 150 + 150 + 50
        self.assertEqual(dec(ctx['refunds_total']), Decimal('300'))  # A + D + legacy C
        self.assertEqual(dec(ctx['total']), Decimal('50'))

    # Shift report (cash drawer)
    def test_shift_counts_refunded_sale_as_cash_taken_that_day(self):
        ctx = self.shift(10)
        self.assertEqual(dec(ctx['cash_sales']), Decimal('100'))
        self.assertEqual(dec(ctx['net_amount']), Decimal('600'))

    def test_shift_deducts_cash_refunds_given_that_day(self):
        ctx = self.shift(11)
        self.assertEqual(dec(ctx['cash_sales']), Decimal('50'))
        self.assertEqual(dec(ctx['cash_refunds']), Decimal('100'))    # GCash refund doesn't leave the drawer
        self.assertEqual(dec(ctx['total_refunds']), Decimal('150'))
        self.assertEqual(dec(ctx['net_amount']), Decimal('450'))      # 500 + 50 − 100

    def test_shift_attributes_refund_to_whoever_gave_it(self):
        self.assertEqual(dec(self.shift(11, cashier=self.manager.pk)['cash_refunds']), Decimal('100'))
        self.assertEqual(dec(self.shift(11, cashier=self.cashier.pk)['cash_refunds']), Decimal('0'))


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

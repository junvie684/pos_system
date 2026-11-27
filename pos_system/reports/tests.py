from datetime import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from sales.models import Sale
from tenants.middleware import tenant_context
from tenants.test_utils import make_product, make_refund, make_sale, make_tenant, make_user, pos_login


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
    databases = {'default', 'archive'}   # reports also read the archive database

    def setUp(self):
        self.tenant = make_tenant('store-a')
        self.manager = make_user(self.tenant, 'manager1', role='manager')
        self.cashier = make_user(self.tenant, 'cashier1')
        product = make_product(self.tenant, price='50.00', stock=100)

        a = make_sale(self.tenant, self.cashier, product, qty=2)
        d = make_sale(self.tenant, self.cashier, product, qty=1)
        b = make_sale(self.tenant, self.cashier, product, qty=1)
        c = make_sale(self.tenant, self.cashier, product, qty=3)
        Sale.all_objects.filter(pk=a.pk).update(created_at=at(10))
        make_refund(a, when=at(11, 15), by=self.manager)
        Sale.all_objects.filter(pk=d.pk).update(created_at=at(10, 11), payment_method='gcash', reference_number='R1')
        make_refund(d, when=at(11, 16), by=self.manager)
        Sale.all_objects.filter(pk=b.pk).update(created_at=at(11))
        # Legacy refund: no refund date or person was recorded, so the
        # conversion dated it to the sale and left "refunded by" empty.
        Sale.all_objects.filter(pk=c.pk).update(created_at=at(9))
        make_refund(c, when=at(9))

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


# ─── Analytics page ─────────────────────────────────────────────
class CashClosingPageTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant('store-a')
        self.manager = make_user(self.tenant, 'manager1', role='manager')
        self.cashier = make_user(self.tenant, 'cashier1')
        soap = make_product(self.tenant, name='Soap', price='50.00', stock=100)
        make_sale(self.tenant, self.cashier, soap, qty=2)
        gcash = make_sale(self.tenant, self.cashier, soap, qty=1)
        Sale.all_objects.filter(pk=gcash.pk).update(payment_method='gcash')
        pos_login(self.client, self.manager)

    def test_names_the_cashier_and_breaks_down_methods(self):
        resp = self.client.get('/reports/shift_report/', {'cashier': self.cashier.pk, 'starting_cash': '500'})
        ctx = resp.context
        self.assertEqual(ctx['cashier_name'], 'cashier1')
        self.assertContains(resp, 'Cashier: cashier1')
        rows = {r['label']: r for r in ctx['method_rows']}
        self.assertEqual(rows['Cash']['amount'], 100.0)
        self.assertTrue(rows['Cash']['is_cash'])
        self.assertEqual(rows['GCash']['count'], 1)
        self.assertEqual(ctx['net_amount'], 600.0)
        self.assertNotContains(resp, '<table')


# ─── Analytics › Performance tab ────────────────────────────────
class PerformanceTests(TestCase):
    """At 7:40 PM on Mar 11, "Today" is compared with Mar 10 until 7:40 PM."""
    databases = {'default', 'archive'}   # reads the archive database too

    def setUp(self):
        self.tenant = make_tenant('store-a')
        self.manager = make_user(self.tenant, 'manager1', role='manager')
        self.product = make_product(self.tenant, price='50.00', stock=100)
        self.now = at(11, 19).replace(minute=40)

    def sale(self, when, qty=1, status='completed'):
        s = make_sale(self.tenant, self.manager, self.product, qty=qty, status=status)
        Sale.all_objects.filter(pk=s.pk).update(created_at=when)
        return s

    def test_today_compares_with_yesterday_to_the_same_time(self):
        from reports.performance import collect
        self.sale(at(11, 10), qty=2)
        self.sale(at(11, 12), qty=1, status='refunded')   # sold, then refunded: still in Sales
        self.sale(at(10, 10), qty=3)
        self.sale(at(10, 21), qty=5)                      # after 7:40 PM: on the chart, not in the change
        self.sale(at(4, 9))                               # same day last week
        with tenant_context(self.tenant.id):              # a store sees only its own sales
            data = collect('today', self.now)

        self.assertEqual((data['so_far'].units, data['so_far'].lines, data['so_far'].revenue), (3, 2, dec('150.00')))
        self.assertEqual((data['prior_so_far'].units, data['prior_so_far'].lines), (3, 1))
        current, prior, last_week, last_year = data['series']
        self.assertEqual(current.buckets[10].units, 2)
        self.assertEqual(prior.buckets[21].units, 5)
        self.assertEqual(last_week.buckets[9].units, 1)
        self.assertEqual(last_year.key, 'last_year')
        self.assertEqual(data['last_bucket'], 19)
        self.assertEqual(data['so_far'].value('units_per_line'), dec('1.5'))
        self.assertEqual(data['so_far'].value('sales_per_line'), dec('75'))

    def test_shorter_prior_month_has_no_points_past_its_end(self):
        from reports.performance import collect
        with tenant_context(self.tenant.id):
            data = collect('month', at(15))
        self.assertEqual(data['n'], 31)                   # March
        self.assertEqual(data['lengths']['prior'], 28)    # February 2026
        self.assertEqual(data['lengths']['last_year'], 31)

    def test_page_renders_every_period_and_figure(self):
        from reports.performance import METRICS, PERIODS
        self.sale(timezone.now() - timezone.timedelta(minutes=5), qty=2)
        pos_login(self.client, self.manager)
        resp = self.client.get('/reports/analytics/')
        self.assertContains(resp, 'Real-time sales performance')
        self.assertContains(resp, 'Today so far')
        for period in PERIODS:
            for metric in METRICS:
                with self.subTest(period=period, metric=metric):
                    r = self.client.get(f'/reports/analytics/?period={period}&metric={metric}')
                    self.assertEqual(r.status_code, 200)
        r = self.client.get('/reports/analytics/?period=bogus&metric=bogus')
        self.assertEqual(r.context['period'], 'today')
        self.assertEqual(r.context['metric'], 'units')

    def test_csv_export(self):
        self.sale(timezone.now() - timezone.timedelta(minutes=5), qty=2)
        pos_login(self.client, self.manager)
        resp = self.client.get('/reports/analytics/?period=7d&export=csv')
        self.assertEqual(resp['Content-Type'], 'text/csv')
        body = resp.content.decode()
        self.assertIn('Sales / order item', body)
        self.assertIn('Previous 7 days (same point)', body)

    def test_old_tab_links_open_the_report(self):
        pos_login(self.client, self.manager)
        for mode in ('daily', 'weekly', 'monthly'):
            with self.subTest(mode=mode):
                self.assertContains(self.client.get(f'/reports/analytics/?mode={mode}'),
                                    'Real-time sales performance')

    def test_needs_reports_access(self):
        cashier = make_user(self.tenant, 'cashier1')
        pos_login(self.client, cashier)
        resp = self.client.get('/reports/analytics/')
        self.assertEqual(resp.status_code, 302)


# ─── Analytics › Trends tab ─────────────────────────────────────
class TrendsTests(TestCase):
    """Friday Nov 27, 2026: the last complete week is Wk 47 (Nov 16–22)."""
    databases = {'default', 'archive'}   # reads the archive database too

    def setUp(self):
        self.tenant = make_tenant('store-a')
        self.manager = make_user(self.tenant, 'manager1', role='manager')
        self.product = make_product(self.tenant, price='50.00', stock=100)

    def sale(self, when, qty=1):
        s = make_sale(self.tenant, self.manager, self.product, qty=qty)
        Sale.all_objects.filter(pk=s.pk).update(created_at=when)

    def test_periods_are_complete_and_matched_a_year_back(self):
        from datetime import date
        from reports.trends import build_periods
        today = date(2026, 11, 27)
        weeks = build_periods('weekly', today)
        self.assertEqual(len(weeks), 8)
        self.assertEqual((weeks[-1].label, weeks[-1].start, weeks[-1].end),
                         ('Wk 47', date(2026, 11, 16), date(2026, 11, 23)))
        self.assertEqual(weeks[-1].ly_start, date(2025, 11, 17))     # Wk 47 of 2025
        months = build_periods('monthly', today)
        self.assertEqual([m.label for m in months], ['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'])
        self.assertEqual(months[0].ly_start, date(2025, 5, 1))
        quarters = build_periods('quarterly', today)
        self.assertEqual([(q.label, q.start) for q in quarters],
                         [('Q4 2025', date(2025, 10, 1)), ('Q1 2026', date(2026, 1, 1)),
                          ('Q2 2026', date(2026, 4, 1)), ('Q3 2026', date(2026, 7, 1))])

    def test_totals_per_week_and_last_year_leave_out_this_week(self):
        from reports.trends import collect
        self.sale(timezone.make_aware(datetime(2026, 11, 18, 10)), qty=3)   # Wk 47
        self.sale(timezone.make_aware(datetime(2025, 11, 18, 10)), qty=2)   # Wk 47 last year
        self.sale(timezone.make_aware(datetime(2026, 11, 24, 10)), qty=9)   # this week: not complete
        with tenant_context(self.tenant.id):
            data = collect('weekly', timezone.make_aware(datetime(2026, 11, 27, 15)))
        self.assertEqual(data['current'][-1].units, 3)
        self.assertEqual(data['last_year'][-1].units, 2)
        self.assertEqual(sum(t.units for t in data['current']), 3)

    def test_page_renders_every_cadence_and_figure_with_tabs(self):
        from reports.performance import METRICS
        from reports.trends import CADENCES
        pos_login(self.client, self.manager)
        resp = self.client.get('/reports/analytics/?tab=trends')
        self.assertContains(resp, 'Business trends year over year')
        self.assertContains(resp, 'class="module-tab is-on" aria-current="page">\n    <i class="bi bi-bar-chart-line"')
        for cadence in CADENCES:
            for metric in METRICS:
                with self.subTest(cadence=cadence, metric=metric):
                    r = self.client.get('/reports/analytics/', {'tab': 'trends', 'cadence': cadence,
                                                                'metric': metric, 'compare': metric, 'yoy': metric})
                    self.assertEqual(r.status_code, 200)
        r = self.client.get('/reports/analytics/', {'tab': 'trends', 'cadence': 'x', 'metric': 'x'})
        self.assertEqual((r.context['cadence'], r.context['m1']), ('weekly', 'revenue'))
        # The Performance tab shows the same tab bar
        self.assertContains(self.client.get('/reports/analytics/'), 'href="?tab=trends"')

    def test_csv_export(self):
        pos_login(self.client, self.manager)
        resp = self.client.get('/reports/analytics/?tab=trends&cadence=monthly&export=csv')
        self.assertEqual(resp['Content-Type'], 'text/csv')
        self.assertIn('Sales last year', resp.content.decode())

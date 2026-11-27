from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from archive.models import ArchivedSale, ArchivedSaleItem
from archive.services import archive_store
from customers.models import Customer
from sales.models import Sale, SaleItem
from tenants.middleware import tenant_context
from tenants.models import Tenant
from tenants.test_utils import (
    make_refund,
    PASSWORD, make_platform_admin, make_product, make_sale, make_tenant, make_user, pos_login,
)

BOTH_DBS = {'default', 'archive'}


def age(sale, days):
    Sale.all_objects.filter(pk=sale.pk).update(created_at=timezone.now() - timedelta(days=days))


class ArchiverTests(TestCase):
    databases = BOTH_DBS

    def setUp(self):
        self.store = make_tenant('store-a')
        Tenant.objects.filter(pk=self.store.pk).update(retention_days=90, auto_archive=True)
        self.store.refresh_from_db()
        self.cashier = make_user(self.store, 'till1')
        self.product = make_product(self.store, name='Pandesal', price='45.00')
        self.customer = Customer.all_objects.create(tenant_id=self.store.id, name='Aling Nena')

    def old_sale(self, days=120, **kw):
        sale = make_sale(self.store, self.cashier, self.product, qty=2, **kw)
        Sale.all_objects.filter(pk=sale.pk).update(customer=self.customer, or_number=sale.pk)
        age(sale, days)
        return sale

    def test_old_paid_sale_moves_with_a_full_copy(self):
        sale = self.old_sale()
        self.assertEqual(archive_store(self.store), 1)
        self.assertFalse(Sale.all_objects.filter(pk=sale.pk).exists())
        self.assertFalse(SaleItem.all_objects.filter(sale_id=sale.pk).exists())
        copy = ArchivedSale.all_objects.get(pk=sale.pk)
        self.assertEqual((copy.total, copy.customer_name, copy.cashier_name, copy.or_number),
                         (Decimal('90.00'), 'Aling Nena', 'till1', sale.pk))
        line = ArchivedSaleItem.all_objects.get(sale_id=sale.pk)
        self.assertEqual((line.product_name, line.quantity), ('Pandesal', 2))

    def test_saved_cost_moves_with_the_line(self):
        sale = self.old_sale()
        SaleItem.all_objects.filter(sale_id=sale.pk).update(unit_cost=Decimal('30.00'))
        archive_store(self.store)
        self.assertEqual(ArchivedSaleItem.all_objects.get(sale_id=sale.pk).unit_cost, Decimal('30.00'))

    def test_recent_and_held_sales_stay(self):
        recent = self.old_sale(days=30)
        held = self.old_sale(days=400, status='pending')
        self.assertEqual(archive_store(self.store), 0)
        self.assertTrue(Sale.all_objects.filter(pk__in=[recent.pk, held.pk]).count() == 2)

    def test_refunded_sales_are_archived_too(self):
        sale = self.old_sale(status='refunded')
        archive_store(self.store)
        self.assertEqual(ArchivedSale.all_objects.get(pk=sale.pk).status, 'refunded')

    def test_part_refunds_move_with_their_sale(self):
        from archive.models import ArchivedRefund
        from sales.models import Refund, RefundItem
        sale = self.old_sale()                       # 2 x the product
        make_refund(sale, qty=1, restocked=False)    # one of the two came back, damaged
        archive_store(self.store)
        self.assertFalse(Refund.all_objects.exists())
        self.assertFalse(RefundItem.all_objects.exists())
        with tenant_context(self.store.id):
            copy = ArchivedRefund.objects.get(sale_id=sale.pk)
            line = copy.items.get()
            self.assertEqual((copy.total, line.quantity, line.restocked, line.product_name),
                             (self.product.price, 1, False, self.product.name))
            archived = ArchivedSale.objects.get(pk=sale.pk)
            self.assertEqual(archived.status, 'completed')
            self.assertEqual(archived.kept_total, self.product.price)

    def test_rerun_replaces_a_leftover_copy(self):
        sale = self.old_sale()
        ArchivedSale.all_objects.create(pk=sale.pk, tenant_id=self.store.id, status='completed',
                                        payment_method='cash', created_at=timezone.now(),
                                        total=Decimal('1.00'))
        archive_store(self.store)
        self.assertEqual(ArchivedSale.all_objects.get(pk=sale.pk).total, Decimal('90.00'))
        self.assertEqual(ArchivedSaleItem.all_objects.filter(sale_id=sale.pk).count(), 1)

    def test_other_stores_are_untouched(self):
        other = make_tenant('store-b')
        theirs = make_sale(other, make_user(other, 'b1'), make_product(other, name='X'))
        age(theirs, 400)
        archive_store(self.store)
        self.assertTrue(Sale.all_objects.filter(pk=theirs.pk).exists())

    def test_or_numbers_continue_after_everything_is_archived(self):
        Tenant.objects.filter(pk=self.store.pk).update(last_or_number=41)
        self.old_sale()
        archive_store(self.store)
        fresh = Sale.all_objects.create(tenant_id=self.store.id, cashier=self.cashier)
        fresh.assign_or_number()
        self.assertEqual(fresh.or_number, 42)

    def test_archive_is_scoped_to_the_current_store(self):
        self.old_sale()
        archive_store(self.store)
        self.assertEqual(ArchivedSale.objects.count(), 0)          # no store in context
        with tenant_context(self.store.id):
            self.assertEqual(ArchivedSale.objects.count(), 1)

    def test_run_is_recorded_on_the_store(self):
        self.old_sale()
        archive_store(self.store)
        self.store.refresh_from_db()
        self.assertEqual(self.store.last_archive_count, 1)
        self.assertIsNotNone(self.store.last_archived_at)


class ArchiveCommandTests(TestCase):
    databases = BOTH_DBS

    def setUp(self):
        self.auto = make_tenant('auto-store')
        self.manual = make_tenant('manual-store')
        Tenant.objects.filter(pk=self.auto.pk).update(auto_archive=True, archive_hour=timezone.localtime().hour)
        for store in (self.auto, self.manual):
            sale = make_sale(store, make_user(store, f'{store.slug}-till'), make_product(store, name=store.slug))
            age(sale, 400)

    def run_cmd(self, *args):
        out = StringIO()
        call_command('archive_sales', *args, stdout=out)
        return out.getvalue()

    def test_nightly_run_only_touches_auto_stores(self):
        self.run_cmd()
        self.assertEqual(Sale.all_objects.filter(tenant_id=self.auto.id).count(), 0)
        self.assertEqual(Sale.all_objects.filter(tenant_id=self.manual.id).count(), 1)

    def test_store_option_archives_a_manual_store(self):
        self.run_cmd('--store', 'manual-store')
        self.assertEqual(Sale.all_objects.filter(tenant_id=self.manual.id).count(), 0)

    def test_dry_run_moves_nothing(self):
        out = self.run_cmd('--dry-run')
        self.assertIn('would move 1', out)
        self.assertEqual(Sale.all_objects.count(), 2)


class PlatformRetentionTests(TestCase):
    databases = BOTH_DBS
    AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}

    def setUp(self):
        self.store = make_tenant('store-a')
        make_platform_admin()
        self.client.post('/platform/login/', {'username': 'platform', 'password': PASSWORD})

    def save(self, days, auto='1'):
        return self.client.post(f'/platform/store/{self.store.id}/retention/',
                                {'retention_days': days, 'auto_archive': auto}, **self.AJAX).json()

    def test_retention_and_auto_archive_are_saved(self):
        self.assertTrue(self.save(180)['success'])
        self.store.refresh_from_db()
        self.assertEqual((self.store.retention_days, self.store.auto_archive), (180, True))

    def test_retention_below_the_minimum_is_refused(self):
        result = self.save(30)
        self.assertFalse(result['success'])
        self.store.refresh_from_db()
        self.assertEqual(self.store.retention_days, 365)

    def test_store_page_shows_the_retention_card(self):
        page = self.client.get(f'/platform/store/{self.store.id}/')
        self.assertContains(page, 'Data retention')
        self.assertEqual(page.context['retention']['waiting'], 0)

    def test_archive_now_moves_sales_even_when_auto_is_off(self):
        sale = make_sale(self.store, make_user(self.store, 'till1'), make_product(self.store))
        age(sale, 400)
        self.client.post(f'/platform/store/{self.store.id}/archive/')
        self.assertTrue(ArchivedSale.all_objects.filter(pk=sale.pk).exists())


class ArchivedSalesInPosTests(TestCase):
    databases = BOTH_DBS

    def setUp(self):
        self.store = make_tenant('store-a')
        self.manager = make_user(self.store, 'mgr', role='manager', can_access_reports=True)
        self.cashier = make_user(self.store, 'till1')
        product = make_product(self.store, name='Pandesal', price='45.00')
        self.sale = make_sale(self.store, self.cashier, product, qty=2)
        Sale.all_objects.filter(pk=self.sale.pk).update(or_number=7)
        age(self.sale, 400)
        self.sold_on = timezone.localdate(timezone.now() - timedelta(days=400))
        archive_store(self.store)
        pos_login(self.client, self.manager)

    def history(self, **params):
        return self.client.get('/history/', params)

    def test_archived_sale_is_listed_in_sales_history_with_a_badge(self):
        page = self.history()
        self.assertEqual([s.pk for s in page.context['sales']], [self.sale.pk])
        self.assertContains(page, 'class="hx-archived"')
        self.assertContains(page, f'/archive/{self.sale.pk}/receipt/')

    def test_archived_sale_cannot_be_refunded_from_history(self):
        page = self.history()
        self.assertNotContains(page, f'openRefundModal({self.sale.pk})')
        self.assertContains(page, "Archived sales can't be refunded")

    def test_history_search_finds_archived_sale_by_or_number(self):
        page = self.history(q='OR-000007')
        self.assertEqual([s.pk for s in page.context['sales']], [self.sale.pk])

    def test_history_totals_include_archived_sales(self):
        page = self.history()
        self.assertEqual(page.context['filtered_total'], Decimal('90.00'))
        self.assertEqual(page.context['filtered_count'], 1)

    def test_current_sales_come_before_archived_across_pages(self):
        product = make_product(self.store, name='Kape', price='20.00')
        recent = [make_sale(self.store, self.cashier, product) for _ in range(26)]
        first = self.history()
        self.assertEqual(first.context['sales'].paginator.count, 27)
        self.assertFalse(any(getattr(s, 'is_archived', False) for s in first.context['sales']))
        second = self.history(page=2)
        self.assertEqual([s.pk for s in second.context['sales']], [recent[0].pk, self.sale.pk])

    def test_archived_receipt_reprints(self):
        page = self.client.get(f'/archive/{self.sale.pk}/receipt/')
        self.assertContains(page, 'OR-000007')
        self.assertContains(page, 'Pandesal')
        self.assertContains(page, 'Reprinted from archive')

    def test_other_stores_cannot_open_the_receipt(self):
        other = make_tenant('store-b')
        self.client.post('/accounts/logout/')
        pos_login(self.client, make_user(other, 'mgr-b', role='manager', can_access_reports=True))
        self.assertEqual(self.client.get(f'/archive/{self.sale.pk}/receipt/').status_code, 404)

    def test_daily_report_includes_archived_sales(self):
        page = self.client.get('/reports/', {'day': self.sold_on.isoformat()})
        self.assertEqual(page.context['gross_sales'], Decimal('90.00'))
        self.assertEqual(page.context['transaction_count'], 1)
        self.assertFalse(page.context['archive_unavailable'])

    def test_sale_in_both_databases_is_counted_once(self):
        # A run that stopped after the archive copy: the sale is back in main too.
        Sale.all_objects.create(pk=self.sale.pk, tenant_id=self.store.id, cashier=self.cashier,
                                status='completed')
        Sale.all_objects.filter(pk=self.sale.pk).update(created_at=timezone.now() - timedelta(days=400))
        SaleItem.all_objects.create(tenant_id=self.store.id, sale_id=self.sale.pk,
                                    product=make_product(self.store, name='Dup'), quantity=2,
                                    unit_price=Decimal('45.00'))
        page = self.client.get('/reports/', {'day': self.sold_on.isoformat()})
        self.assertEqual(page.context['transaction_count'], 1)
        self.assertEqual(page.context['gross_sales'], Decimal('90.00'))


class ArchiveIntervalTests(TestCase):
    """Each store sets how often automatic archiving runs."""
    databases = BOTH_DBS

    def setUp(self):
        self.store = make_tenant('weekly-store')
        Tenant.objects.filter(pk=self.store.pk).update(auto_archive=True, archive_every_days=7,
                                                       archive_hour=timezone.localtime().hour)
        sale = make_sale(self.store, make_user(self.store, 'till'), make_product(self.store))
        age(sale, 400)

    def ran_days_ago(self, days):
        Tenant.objects.filter(pk=self.store.pk).update(last_archived_at=timezone.now() - timedelta(days=days))

    def nightly(self, *args):
        out = StringIO()
        call_command('archive_sales', *args, stdout=out)
        return out.getvalue()

    def test_store_is_skipped_until_its_interval_has_passed(self):
        self.ran_days_ago(3)
        self.assertIn('next run', self.nightly())
        self.assertEqual(Sale.all_objects.filter(tenant_id=self.store.id).count(), 1)

    def test_store_runs_once_the_interval_has_passed(self):
        self.ran_days_ago(7)
        self.nightly()
        self.assertEqual(Sale.all_objects.filter(tenant_id=self.store.id).count(), 0)

    def test_never_archived_store_runs_on_the_first_night(self):
        self.nightly()
        self.assertEqual(Sale.all_objects.filter(tenant_id=self.store.id).count(), 0)

    def test_store_option_ignores_the_interval(self):
        self.ran_days_ago(1)
        self.nightly('--store', 'weekly-store')
        self.assertEqual(Sale.all_objects.filter(tenant_id=self.store.id).count(), 0)

    def test_platform_saves_and_validates_the_interval(self):
        make_platform_admin()
        self.client.post('/platform/login/', {'username': 'platform', 'password': PASSWORD})
        url = f'/platform/store/{self.store.id}/retention/'
        ajax = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        ok = self.client.post(url, {'retention_days': 365, 'archive_every_days': 14, 'auto_archive': '1'}, **ajax).json()
        self.assertTrue(ok['success'])
        self.store.refresh_from_db()
        self.assertEqual(self.store.archive_every_days, 14)
        bad = self.client.post(url, {'retention_days': 365, 'archive_every_days': 0, 'auto_archive': '1'}, **ajax).json()
        self.assertFalse(bad['success'])
        self.assertIn('archive_every_days', bad['errors'])


class ArchiveHourTests(TestCase):
    """Each store archives at its own hour (store time); the job runs hourly."""
    databases = BOTH_DBS

    def setUp(self):
        self.store = make_tenant('store-a')
        Tenant.objects.filter(pk=self.store.pk).update(auto_archive=True, archive_hour=2, archive_every_days=1)
        self.store.refresh_from_db()

    def at(self, day, hour, minute=0):
        return timezone.make_aware(datetime(2026, 11, day, hour, minute))

    def test_runs_only_during_its_hour(self):
        self.assertTrue(self.store.archive_is_due(self.at(23, 2, 5)))
        self.assertFalse(self.store.archive_is_due(self.at(23, 1, 59)))
        self.assertFalse(self.store.archive_is_due(self.at(23, 3, 0)))

    def test_waits_for_its_interval(self):
        self.store.archive_every_days = 7
        self.store.last_archived_at = self.at(20, 2, 3)
        self.assertFalse(self.store.archive_is_due(self.at(26, 2)))
        self.assertTrue(self.store.archive_is_due(self.at(27, 2)))

    def test_next_run_is_tomorrow_once_today_s_hour_has_passed(self):
        self.store.last_archived_at = self.at(22, 2, 1)
        self.assertEqual(self.store.next_archive_run(self.at(22, 9)), self.at(23, 2))
        self.assertEqual(self.store.next_archive_run(self.at(23, 1)), self.at(23, 2))

    def test_store_at_another_hour_is_skipped_by_the_job(self):
        Tenant.objects.filter(pk=self.store.pk).update(archive_hour=(timezone.localtime().hour + 12) % 24)
        sale = make_sale(self.store, make_user(self.store, 'till'), make_product(self.store))
        age(sale, 400)
        call_command('archive_sales', stdout=StringIO())
        self.assertTrue(Sale.all_objects.filter(pk=sale.pk).exists())


class AnalyticsArchiveTests(TestCase):
    """Analytics compares with the same day last year, which may be archived."""
    databases = BOTH_DBS

    def setUp(self):
        self.store = make_tenant('store-a')
        self.manager = make_user(self.store, 'mgr', role='manager', can_access_reports=True)
        pandesal = make_product(self.store, name='Pandesal', price='45.00')
        sale = make_sale(self.store, self.manager, pandesal, qty=2)
        self.when = timezone.localtime(timezone.now())
        last_year = self.when.replace(year=self.when.year - 1) if not (self.when.month == 2 and self.when.day == 29)             else self.when.replace(year=self.when.year - 1, day=28)
        Sale.all_objects.filter(pk=sale.pk).update(created_at=last_year)
        archive_store(self.store)

    def test_same_day_last_year_includes_the_archived_sale(self):
        from reports.performance import collect
        self.assertEqual(ArchivedSale.all_objects.count(), 1)
        with tenant_context(self.store.id):
            data = collect('today', self.when)
        last_year = next(s for s in data['series'] if s.key == 'last_year')
        self.assertEqual(sum(b.units for b in last_year.buckets), 2)
        self.assertEqual(sum(b.revenue for b in last_year.buckets), Decimal('90.00'))
        self.assertTrue(data['archive_ok'])


class DashboardArchiveTests(TestCase):
    """The dashboard tiles and product table count archived sales too."""
    databases = BOTH_DBS

    def setUp(self):
        self.store = make_tenant('store-a')
        self.manager = make_user(self.store, 'mgr', role='manager', can_access_reports=True)
        self.cashier = make_user(self.store, 'till1')
        pandesal = make_product(self.store, name='Pandesal', price='45.00')
        old = make_sale(self.store, self.cashier, pandesal, qty=2)
        refunded = make_sale(self.store, self.cashier, pandesal, qty=1, status='refunded')
        age(old, 400)
        age(refunded, 400)
        archive_store(self.store)
        make_sale(self.store, self.cashier, pandesal, qty=1)   # still in the main database
        pos_login(self.client, self.manager)
        today = timezone.localdate()
        self.span = {'preset': 'custom', 'from': (today - timedelta(days=500)).isoformat(),
                     'to': today.isoformat()}

    def test_tiles_and_products_include_archived_sales(self):
        ctx = self.client.get('/', self.span).context
        self.assertEqual(ArchivedSale.all_objects.count(), 2)
        tile = ctx['tiles'][0]
        self.assertEqual((tile['sales'], tile['txns'], tile['units']), (Decimal('180.00'), 3, 4))
        pandesal = ctx['rows'][0]
        self.assertEqual((pandesal['name'], pandesal['units'], pandesal['sales']),
                         ('Pandesal', 4, Decimal('180.00')))
        self.assertFalse(ctx['archive_unavailable'])

    def test_order_items_include_archived_lines(self):
        ctx = self.client.get('/', {**self.span, 'view': 'items'}).context
        self.assertEqual(ctx['line_total'], 3)

    def test_sale_caught_mid_move_is_counted_once(self):
        # Simulate a run that copied a sale but stopped before deleting it.
        archived = ArchivedSale.all_objects.filter(status="completed").get()
        live = make_sale(self.store, self.cashier, make_product(self.store, name='Kape', price='30.00'))
        ArchivedSale.all_objects.filter(pk=archived.pk).update(id=live.pk)
        ArchivedSaleItem.all_objects.filter(sale_id=archived.pk).update(sale_id=live.pk)
        ctx = self.client.get('/', self.span).context
        self.assertEqual(ctx['tiles'][0]['txns'], 3)   # live sale, its archived copy skipped, + refunded

    def test_dashboard_still_renders_when_archive_is_down(self):
        from unittest import mock
        from django.db import DatabaseError
        with mock.patch('reports.pnl.archived_sales_made', side_effect=DatabaseError),              mock.patch('reports.tiles.archived_sales_made', side_effect=DatabaseError):
            resp = self.client.get('/', self.span)
        self.assertTrue(resp.context['archive_unavailable'])
        self.assertContains(resp, "archive database isn't reachable")
        self.assertEqual(resp.context['tiles'][0]['txns'], 1)

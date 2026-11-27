from decimal import Decimal

from django.test import TestCase

from products.models import Product
from tenants.test_utils import make_product, make_tenant, make_user, pos_login

AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class ProductCostTests(TestCase):
    """Each product can carry its cost per unit (COGS); it's optional."""
    databases = {'default', 'archive'}   # the Products tab's figures read the archive too

    def setUp(self):
        self.tenant = make_tenant('store-a')
        self.manager = make_user(self.tenant, 'manager1', role='manager')
        pos_login(self.client, self.manager)

    def post(self, url, **fields):
        data = {'name': 'Soap', 'category': '', 'price': '50.00', 'cost': '', 'stock': '10', 'barcode': '', **fields}
        return self.client.post(url, data, **AJAX).json()

    def test_add_with_and_without_cost(self):
        with_cost = self.post('/products/add/', cost='32.50')
        self.assertTrue(with_cost['success'])
        self.assertEqual(with_cost['product']['cost'], '32.50')
        self.assertEqual(Product.all_objects.get(pk=with_cost['product']['pk']).cost, Decimal('32.50'))

        without = self.post('/products/add/', name='Rice', cost='')
        self.assertTrue(without['success'])
        self.assertEqual(without['product']['cost'], '')
        self.assertIsNone(Product.all_objects.get(pk=without['product']['pk']).cost)

    def test_edit_sets_and_clears_cost(self):
        product = make_product(self.tenant)
        data = self.post(f'/products/edit/{product.pk}/', cost='20')
        self.assertEqual(data['product']['cost'], '20.00')
        self.post(f'/products/edit/{product.pk}/', cost='')
        product.refresh_from_db()
        self.assertIsNone(product.cost)

    def test_negative_cost_is_refused(self):
        data = self.post('/products/add/', cost='-1')
        self.assertFalse(data['success'])
        self.assertIn('cost', data['errors'])

    def test_list_shows_the_cost_column(self):
        product = make_product(self.tenant, name='Soap')
        Product.all_objects.filter(pk=product.pk).update(cost=Decimal('31.25'))
        make_product(self.tenant, name='Rice')                      # no cost yet
        resp = self.client.get('/products/')
        self.assertContains(resp, 'Cost (COGS)</th>')
        self.assertContains(resp, '<td class="fig num row-cost">₱31.25</td>', html=False)
        self.assertContains(resp, '<td class="fig num row-cost"><span class="rx-muted">—</span></td>', html=False)


class ProductHistoryCostTests(TestCase):
    """Product history shows the cost of the units sold: units × current unit cost."""
    databases = {'default', 'archive'}   # history also reads the archive database

    def setUp(self):
        from tenants.test_utils import make_sale
        self.tenant = make_tenant('store-a')
        self.manager = make_user(self.tenant, 'manager1', role='manager')
        self.product = make_product(self.tenant, name='Soap', price='50.00', stock=100)
        make_sale(self.tenant, self.manager, self.product, qty=3)
        make_sale(self.tenant, self.manager, self.product, qty=2)
        pos_login(self.client, self.manager)

    def test_sales_without_a_saved_cost_use_todays_cost(self):
        # setUp's sales were made with no saved cost, like sales from before this feature
        Product.all_objects.filter(pk=self.product.pk).update(cost=Decimal('31.50'))
        resp = self.client.get(f'/products/{self.product.pk}/history/')
        self.assertEqual(resp.context['totals']['total_cost'], Decimal('157.50'))   # 5 × 31.50
        self.assertContains(resp, 'Total cost (COGS)')
        self.assertContains(resp, '₱157.50')
        self.assertTrue(resp.context['totals']['cost_note'].startswith("5 units at today's cost"))
        csv_body = self.client.get(f'/products/{self.product.pk}/history/?export=csv').content.decode()
        self.assertIn('Total cost (COGS),157.50', csv_body)

    def test_checkout_saves_the_cost_and_later_changes_dont_rewrite_it(self):
        from sales.models import SaleItem
        from tenants.test_utils import sale_post
        SaleItem.all_objects.filter(product=self.product).delete()      # start clean
        Product.all_objects.filter(pk=self.product.pk).update(cost=Decimal('30.00'))
        self.client.post('/new/', sale_post([(self.product, 2, '50.00')], cash_tendered='100.00'))
        line = SaleItem.all_objects.get(product=self.product)
        self.assertEqual(line.unit_cost, Decimal('30.00'))

        Product.all_objects.filter(pk=self.product.pk).update(cost=Decimal('45.00'))   # cost goes up later
        self.client.post('/new/', sale_post([(self.product, 1, '50.00')], cash_tendered='50.00'))
        resp = self.client.get(f'/products/{self.product.pk}/history/')
        self.assertEqual(resp.context['totals']['total_cost'], Decimal('105.00'))   # 2 × 30 + 1 × 45
        self.assertContains(resp, 'at the cost when each sale was made')

    def test_no_unit_cost_says_so(self):
        resp = self.client.get(f'/products/{self.product.pk}/history/')
        self.assertIsNone(resp.context['totals']['total_cost'])
        self.assertContains(resp, 'No unit cost set')


class ProductGrossProfitTests(TestCase):
    """Gross profit = revenue − cost of the same units; units without any cost are left out."""
    databases = {'default', 'archive'}

    def setUp(self):
        self.tenant = make_tenant('store-a')
        self.manager = make_user(self.tenant, 'manager1', role='manager')
        self.product = make_product(self.tenant, name='Soap', price='50.00', stock=100)
        pos_login(self.client, self.manager)

    def checkout(self, qty, cost):
        from tenants.test_utils import sale_post
        Product.all_objects.filter(pk=self.product.pk).update(cost=cost)
        self.client.post('/new/', sale_post([(self.product, qty, '50.00')], cash_tendered=str(50 * qty)))

    def totals(self):
        return self.client.get(f'/products/{self.product.pk}/history/').context['totals']

    def test_profit_and_margin_at_saved_costs(self):
        self.checkout(2, Decimal('30.00'))      # 100 revenue, 60 cost
        self.checkout(1, Decimal('45.00'))      # 50 revenue, 45 cost
        t = self.totals()
        self.assertEqual((t['gross_profit'], t['margin']), (Decimal('45.00'), Decimal('30.0')))

    def test_units_without_any_cost_are_left_out(self):
        self.checkout(2, None)                  # no cost then, none now
        self.checkout(1, Decimal('20.00'))      # 50 revenue, 20 cost
        Product.all_objects.filter(pk=self.product.pk).update(cost=None)
        t = self.totals()
        self.assertEqual(t['gross_profit'], Decimal('30.00'))
        self.assertEqual(t['profit_note'], 'excludes 2 units without a cost')

    def test_selling_below_cost_shows_a_loss(self):
        self.checkout(1, Decimal('70.00'))
        resp = self.client.get(f'/products/{self.product.pk}/history/')
        self.assertEqual(resp.context['totals']['gross_profit'], Decimal('-20.00'))
        self.assertContains(resp, '−₱20.00')
        self.assertContains(resp, 'Loss')


class ProductsTabFiguresTests(TestCase):
    """The Products tab sums every product, archived sales included."""
    databases = {'default', 'archive'}

    def setUp(self):
        from tenants.test_utils import make_sale
        self.tenant = make_tenant('store-a')
        self.manager = make_user(self.tenant, 'manager1', role='manager')
        soap = make_product(self.tenant, name='Soap', price='50.00', stock=100)
        rice = make_product(self.tenant, name='Rice', price='200.00', stock=100)
        Product.all_objects.filter(pk=soap.pk).update(cost=Decimal('30.00'))
        Product.all_objects.filter(pk=rice.pk).update(cost=Decimal('150.00'))
        make_sale(self.tenant, self.manager, soap, qty=2)    # 100 revenue, 60 cost
        make_sale(self.tenant, self.manager, rice, qty=1)    # 200 revenue, 150 cost
        self.soap = soap

    def test_figures_across_every_product(self):
        pos_login(self.client, self.manager)
        resp = self.client.get('/products/')
        self.assertContains(resp, 'All products')
        fig = resp.context['overview']['fig']
        self.assertEqual((fig.units, fig.revenue, fig.transactions), (3, Decimal('300.00'), 2))
        self.assertEqual((fig.total_cost, fig.gross_profit), (Decimal('210.00'), Decimal('90.00')))
        self.assertEqual(fig.margin, Decimal('30.0'))

    def test_all_time_includes_archived_sales_and_period_is_remembered(self):
        from datetime import timedelta
        from django.utils import timezone
        from archive.services import archive_store
        from sales.models import Sale
        from tenants.test_utils import make_sale
        old = make_sale(self.tenant, self.manager, self.soap, qty=4)        # 200 revenue
        Sale.all_objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=400))
        archive_store(self.tenant)
        pos_login(self.client, self.manager)
        fig = self.client.get('/products/?period=all').context['overview']['fig']
        self.assertEqual((fig.units, fig.revenue, fig.transactions), (7, Decimal('500.00'), 3))
        self.assertTrue(fig.archive_ok)
        # Searching later keeps the chosen period
        self.assertEqual(self.client.get('/products/?q=soap').context['overview']['period'], 'all')

    def test_hidden_without_reports_access(self):
        clerk = make_user(self.tenant, 'clerk', can_access_products=True)    # no Reports access
        pos_login(self.client, clerk)
        resp = self.client.get('/products/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context['overview'])
        self.assertNotContains(resp, 'All products')


class ProductTableProfitTests(TestCase):
    """The product table's Gross profit column: same period and rules as the tiles above it."""
    databases = {'default', 'archive'}

    def setUp(self):
        from tenants.test_utils import make_sale
        self.tenant = make_tenant('store-a')
        self.manager = make_user(self.tenant, 'manager1', role='manager')
        self.soap = make_product(self.tenant, name='Soap', price='50.00', stock=100)
        self.rice = make_product(self.tenant, name='Rice', price='200.00', stock=100)
        self.salt = make_product(self.tenant, name='Salt', price='20.00', stock=100)   # never sold
        Product.all_objects.filter(pk=self.soap.pk).update(cost=Decimal('30.00'))
        make_sale(self.tenant, self.manager, self.soap, qty=2)    # 100 − 60 = 40 profit
        make_sale(self.tenant, self.manager, self.rice, qty=1)    # rice has no cost

    def rows(self):
        resp = self.client.get('/products/')
        return resp, {p.name: p.fig for p in resp.context['products']}

    def test_profit_per_product(self):
        pos_login(self.client, self.manager)
        resp, figs = self.rows()
        self.assertContains(resp, '>Gross profit</th>')
        self.assertEqual((figs['Soap'].gross_profit, figs['Soap'].margin), (Decimal('40.00'), Decimal('40.0')))
        self.assertIsNone(figs['Rice'].gross_profit)          # sold, but no cost
        self.assertEqual(figs['Salt'].units, 0)               # no sales
        self.assertContains(resp, '40.0% margin')
        self.assertContains(resp, 'no cost')

    def test_column_hidden_without_reports_access(self):
        clerk = make_user(self.tenant, 'clerk', can_access_products=True)
        pos_login(self.client, clerk)
        resp = self.client.get('/products/')
        self.assertNotContains(resp, '>Gross profit</th>')
        self.assertNotContains(resp, 'data-profit="1"')
        self.assertFalse(any(hasattr(p, 'fig') for p in resp.context['products']))

from django.test import TestCase

from customers.models import Customer
from products.forms import ProductForm
from products.models import Product
from tenants.middleware import get_current_tenant_id, tenant_context
from tenants.models import Tenant
from tenants.test_utils import (
    PASSWORD, make_category, make_platform_admin, make_product, make_sale, make_tenant,
    make_user, pos_login,
)


# ─── C-1: store admins must not reach platform-wide consoles ────
class PlatformAccessTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant('store-a')
        self.store_admin = make_user(self.tenant, 'storeadmin', role='admin',
                                     can_access_user_management=True)
        self.platform_admin = make_platform_admin()

    def test_store_admin_cannot_log_into_platform(self):
        self.client.post('/platform/login/', {'username': 'storeadmin', 'password': PASSWORD})
        resp = self.client.get('/platform/')
        self.assertNotEqual(resp.status_code, 200)

    def test_store_admin_cannot_log_into_django_admin(self):
        self.client.post('/admin/login/?next=/admin/',
                         {'username': 'storeadmin', 'password': PASSWORD})
        resp = self.client.get('/admin/')
        self.assertNotEqual(resp.status_code, 200)

    def test_store_admin_cannot_delete_other_store(self):
        other = make_tenant('store-b')
        self.client.post('/platform/login/', {'username': 'storeadmin', 'password': PASSWORD})
        self.client.post(f'/platform/store/{other.id}/delete/')
        self.assertTrue(Tenant.objects.filter(pk=other.pk).exists())

    def test_platform_admin_can_use_platform(self):
        self.client.post('/platform/login/', {'username': 'platform', 'password': PASSWORD})
        self.assertEqual(self.client.get('/platform/').status_code, 200)

    def test_platform_store_detail_lists_store_users(self):
        self.client.post('/platform/login/', {'username': 'platform', 'password': PASSWORD})
        resp = self.client.get(f'/platform/store/{self.tenant.id}/')
        self.assertContains(resp, 'storeadmin')

    def test_platform_admin_can_use_django_admin(self):
        self.client.post('/admin/login/?next=/admin/',
                         {'username': 'platform', 'password': PASSWORD})
        self.assertEqual(self.client.get('/admin/').status_code, 200)


# ─── C-9: tenant isolation fails closed ─────────────────────────
class TenantIsolationTests(TestCase):
    def setUp(self):
        self.a = make_tenant('store-a')
        self.b = make_tenant('store-b')
        self.cashier_a = make_user(self.a, 'cashier_a')
        self.cashier_b = make_user(self.b, 'cashier_b')
        self.product_b = make_product(self.b, name='B-Only')
        self.sale_b = make_sale(self.b, self.cashier_b, self.product_b)

    def test_manager_without_tenant_returns_nothing(self):
        with tenant_context(None):
            self.assertEqual(Product.objects.count(), 0)
            self.assertEqual(Product.all_objects.count(), 1)

    def test_tenant_is_cleared_after_request(self):
        pos_login(self.client, self.cashier_b)
        self.client.get('/history/')
        self.assertIsNone(get_current_tenant_id())

    def test_manager_with_tenant_context_is_scoped(self):
        with tenant_context(self.b.id):
            self.assertEqual(list(Product.objects.all()), [self.product_b])
        with tenant_context(self.a.id):
            self.assertEqual(Product.objects.count(), 0)

    def test_pos_login_without_tenant_is_refused(self):
        make_platform_admin('noprofile')
        self.client.post('/accounts/login/', {'username': 'noprofile', 'password': PASSWORD})
        resp = self.client.get('/history/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp['Location'])

    def test_cashier_cannot_open_other_store_receipt(self):
        pos_login(self.client, self.cashier_a)
        self.assertEqual(self.client.get(f'/receipt/{self.sale_b.pk}/').status_code, 404)

    def test_cashier_cannot_edit_other_store_customer(self):
        cust_b = Customer.all_objects.create(tenant_id=self.b.id, name='Bob')
        pos_login(self.client, self.cashier_a)
        resp = self.client.post(f'/customers/edit/{cust_b.pk}/', {'name': 'Hacked'})
        self.assertEqual(resp.status_code, 404)

    def test_product_form_category_choices_are_tenant_scoped(self):
        cat_a = make_category(self.a, 'A-cat')
        cat_b = make_category(self.b, 'B-cat')
        with tenant_context(self.a.id):
            choices = list(ProductForm().fields['category'].queryset)
        self.assertEqual(choices, [cat_a])
        self.assertNotIn(cat_b, choices)

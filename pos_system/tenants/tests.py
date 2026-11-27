from django.contrib.auth.models import User
from django.test import Client, TestCase

from accounts.models import UserProfile

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
    databases = {'default', 'archive'}   # pages also read the archive database

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


# ─── Platform: create store from the dashboard form ─────────────
class CreateStoreTests(TestCase):
    def setUp(self):
        make_platform_admin()
        self.client.post('/platform/login/', {'username': 'platform', 'password': PASSWORD})

    def post(self, **extra):
        data = {'name': 'Downtown Branch', 'slug': '', 'address': 'Colon St, Cebu City',
                'phone': '0917 000 0000', 'tin': '123-456-789-000',
                'owner_email': 'owner@example.com', 'owner_password': PASSWORD, **extra}
        return self.client.post('/platform/stores/create/', data)

    def test_empty_slug_is_generated_from_name(self):
        self.post()
        self.assertEqual(Tenant.objects.get().slug, 'downtown-branch')

    def test_generated_slug_stays_unique(self):
        make_tenant('downtown-branch')
        self.post()
        self.assertTrue(Tenant.objects.filter(slug='downtown-branch-2').exists())

    def test_receipt_details_are_saved(self):
        self.post()
        t = Tenant.objects.get(slug='downtown-branch')
        self.assertEqual((t.address, t.phone, t.tin), ('Colon St, Cebu City', '0917 000 0000', '123-456-789-000'))

    def test_dashboard_counts_deactivated_stores(self):
        Tenant.objects.filter(pk=make_tenant('store-z').pk).update(is_active=False)
        self.assertEqual(self.client.get('/platform/').context['inactive_stores'], 1)


# ─── C-9: tenant isolation fails closed ─────────────────────────
class TenantIsolationTests(TestCase):
    databases = {'default', 'archive'}   # sales history also reads the archive database

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


# ─── One session per app: POS and platform side by side ─────────
class SeparateSessionsTests(TestCase):
    databases = {'default', 'archive'}   # pages also read the archive database

    """Signing in to the POS must not sign the browser out of the platform
    console, and the other way round (they used to share one session)."""

    def setUp(self):
        self.tenant = make_tenant('store-a')
        make_user(self.tenant, 'cashier1', can_access_dashboard=True)
        make_platform_admin()

    def sign_in_both(self, client=None):
        client = client or self.client
        client.post('/platform/login/', {'username': 'platform', 'password': PASSWORD})
        pos_login(client, User.objects.get(username='cashier1'))
        return client

    def test_platform_stays_signed_in_after_pos_sign_in(self):
        self.sign_in_both()
        self.assertEqual(self.client.get('/platform/').status_code, 200)
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_platform_session_uses_its_own_cookie_and_path(self):
        self.client.post('/platform/login/', {'username': 'platform', 'password': PASSWORD})
        cookie = self.client.cookies['platform_session']
        self.assertEqual(cookie['path'], '/platform/')
        self.assertNotIn('pos_session', self.client.cookies)

    def test_pos_sign_out_keeps_platform_session(self):
        self.sign_in_both()
        self.client.post('/accounts/logout/')
        self.assertEqual(self.client.get('/platform/').status_code, 200)
        self.assertEqual(self.client.get('/').status_code, 302)

    def test_platform_sign_out_keeps_pos_session(self):
        self.sign_in_both()
        self.client.post('/platform/logout/')
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertRedirects(self.client.get('/platform/'), '/platform/login/', fetch_redirect_response=False)

    def test_open_platform_page_still_saves_after_pos_sign_in(self):
        """A platform page loaded before the POS sign-in keeps a valid CSRF token."""
        client = Client(enforce_csrf_checks=True)
        token = client.get('/platform/login/').context['csrf_token']
        client.post('/platform/login/', {'username': 'platform', 'password': PASSWORD,
                                         'csrfmiddlewaretoken': token})
        page = client.get(f'/platform/store/{self.tenant.id}/')
        platform_token = str(page.context['csrf_token'])

        pos_token = client.get('/accounts/login/').context['csrf_token']
        client.post('/accounts/login/', {'username': 'cashier1', 'password': PASSWORD,
                                         'csrfmiddlewaretoken': pos_token})

        resp = client.post(f'/platform/store/{self.tenant.id}/edit/',
                           {'name': 'Renamed', 'csrfmiddlewaretoken': platform_token},
                           HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Tenant.objects.get(pk=self.tenant.pk).name, 'Renamed')


# ─── Platform "Add user" honours the form ───────────────────────
class PlatformAddUserTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant('store-a')
        make_platform_admin()
        self.client.post('/platform/login/', {'username': 'platform', 'password': PASSWORD})

    def add(self, **extra):
        data = {'username': 'mgr1', 'password': PASSWORD, 'password2': PASSWORD,
                'role': 'manager', 'first_name': 'Ana', 'last_name': 'Cruz', 'is_active': '1',
                'can_access_products': '1', 'can_access_reports': '1'}
        data.update(extra)
        return self.client.post(f'/platform/store/{self.tenant.id}/users/add/', data,
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()

    def test_role_names_and_permissions_are_saved(self):
        self.assertTrue(self.add()['success'])
        user = User.objects.get(username='mgr1')
        profile = UserProfile.all_objects.get(user=user)
        self.assertEqual((user.is_staff, user.is_superuser, user.get_full_name()), (True, False, 'Ana Cruz'))
        self.assertEqual(profile.tenant_id, self.tenant.id)
        self.assertTrue(profile.can_access_products and profile.can_access_reports)
        self.assertFalse(profile.can_access_user_management)

    def test_mismatched_passwords_are_rejected(self):
        result = self.add(password2='different-pass-123')
        self.assertFalse(result['success'])
        self.assertIn('password2', result['errors'])
        self.assertFalse(User.objects.filter(username='mgr1').exists())

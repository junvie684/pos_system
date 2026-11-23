"""Security fixes from the 2026-11 audit: password rules, login throttling,
per-user access switches enforced on the server, and removed side doors."""
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings

from tenants.test_utils import PASSWORD, make_platform_admin, make_tenant, make_user, pos_login


# ─── 1a. Password rules ─────────────────────────────────────────
# Every place a password is set (POS user form, platform console, password
# resets) runs Django's validate_password, so testing the rules covers them all.
class PasswordRuleTests(SimpleTestCase):
    def test_trivial_passwords_are_rejected(self):
        user = User(username='newbie')
        for weak in ('1', 'password', '12345678', 'newbie12'):
            with self.subTest(weak=weak), self.assertRaises(ValidationError):
                validate_password(weak, user)

    def test_strong_password_is_accepted(self):
        validate_password('Tindahan-2026!', User(username='newbie'))


# ─── 1b. Login throttling ───────────────────────────────────────
@override_settings(LOGIN_FAILURE_LIMIT=3, LOGIN_LOCKOUT_SECONDS=900)
class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tenant = make_tenant('store-a')
        self.cashier = make_user(self.tenant, 'cashier1')

    def fail(self, url, username, times):
        for _ in range(times):
            self.client.post(url, {'username': username, 'password': 'wrong-password'})

    def test_account_locks_after_repeated_failures(self):
        self.fail('/accounts/login/', 'cashier1', 3)
        resp = pos_login(self.client, self.cashier)     # right password, but locked
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Too many failed sign-in attempts')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_username_case_does_not_reset_the_count(self):
        self.fail('/accounts/login/', 'CASHIER1', 3)
        self.assertNotIn('_auth_user_id', pos_login(self.client, self.cashier).wsgi_request.session)

    def test_failures_below_the_limit_do_not_lock(self):
        self.fail('/accounts/login/', 'cashier1', 2)
        self.assertRedirects(pos_login(self.client, self.cashier), '/', fetch_redirect_response=False)

    def test_successful_sign_in_resets_the_count(self):
        self.fail('/accounts/login/', 'cashier1', 2)
        pos_login(self.client, self.cashier)
        self.client.logout()
        self.fail('/accounts/login/', 'cashier1', 2)
        self.assertRedirects(pos_login(self.client, self.cashier), '/', fetch_redirect_response=False)

    def test_lock_is_per_account(self):
        other = make_user(self.tenant, 'cashier2')
        self.fail('/accounts/login/', 'cashier1', 3)
        self.assertRedirects(pos_login(self.client, other), '/', fetch_redirect_response=False)

    def test_failures_on_other_login_pages_count_too(self):
        make_platform_admin('platform')
        self.fail('/platform/login/', 'platform', 2)
        self.fail('/admin/login/', 'platform', 1)
        resp = self.client.post('/platform/login/', {'username': 'platform', 'password': PASSWORD})
        self.assertContains(resp, 'Too many failed sign-in attempts')


# ─── 2. Access switches decide access to their pages ────────────
class AccessSwitchTests(TestCase):
    databases = '__all__'   # reports also read the archive database

    PAGES = {
        'can_access_products':     ['/products/'],
        'can_access_categories':   ['/products/categories/'],
        'can_access_reports':      ['/reports/', '/reports/monthly/', '/reports/analytics/'],
        'can_access_shift_report': ['/reports/shift_report/'],
    }

    def setUp(self):
        self.tenant = make_tenant('store-a')

    def test_manager_with_switch_off_is_turned_away(self):
        for flag, urls in self.PAGES.items():
            user = make_user(self.tenant, f'mgr-{flag}', role='manager', **{flag: False})
            self.client.force_login(user)
            session = self.client.session
            session.update({'tenant_id': str(self.tenant.id), 'app_type': 'pos'})
            session.save()
            for url in urls:
                with self.subTest(flag=flag, url=url):
                    resp = self.client.get(url)
                    self.assertEqual(resp.status_code, 302)
                    self.assertNotIn(url, resp['Location'])

    def test_switch_on_opens_the_page_for_any_role(self):
        for flag, urls in self.PAGES.items():
            user = make_user(self.tenant, f'cashier-{flag}', role='cashier', **{flag: True})
            self.client.logout()
            pos_login(self.client, user)
            for url in urls:
                with self.subTest(flag=flag, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_switched_off_writes_are_refused(self):
        from tenants.test_utils import make_category, make_product
        manager = make_user(self.tenant, 'mgr', role='manager',
                            can_access_products=False, can_access_categories=False)
        product = make_product(self.tenant)
        category = make_category(self.tenant)
        pos_login(self.client, manager)
        self.client.post(f'/products/delete/{product.pk}/')
        self.client.post(f'/products/categories/delete/{category.pk}/')
        product.refresh_from_db()
        self.assertTrue(product.is_active)
        self.assertTrue(type(category).all_objects.filter(pk=category.pk).exists())


# ─── 3 & 4. Side doors removed ──────────────────────────────────
class RemovedEndpointTests(TestCase):
    def test_platform_console_is_not_mounted_under_stores(self):
        self.assertEqual(self.client.get('/stores/platform/login/').status_code, 404)

    def test_token_login_api_is_gone(self):
        self.assertEqual(self.client.post('/stores/api/login/').status_code, 404)

    def test_bearer_token_does_not_pick_a_store(self):
        import jwt
        from django.conf import settings
        from tenants.middleware import TenantMiddleware, get_current_tenant_id
        from django.test import RequestFactory
        from django.contrib.auth.models import AnonymousUser

        tenant = make_tenant('store-a')
        token = jwt.encode({'tenant_id': str(tenant.id)}, settings.SECRET_KEY, algorithm='HS256')
        request = RequestFactory().get('/', HTTP_AUTHORIZATION=f'Bearer {token}')
        request.session, request.user = {}, AnonymousUser()
        seen = []
        TenantMiddleware(lambda r: seen.append(get_current_tenant_id()))(request)
        self.assertEqual(seen, [None])

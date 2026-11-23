from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import UserProfile
from tenants.test_utils import PASSWORD, make_tenant, make_user, pos_login


class CashierSignInTemplateTests(TestCase):
    def test_sign_in_exposes_a_focused_terminal_landmark(self):
        response = self.client.get('/accounts/login/')

        self.assertContains(response, 'data-cashier-screen="sign-in"')
        self.assertContains(response, 'aria-labelledby="login-title"')
        self.assertContains(response, 'id="login-title"')

    def test_sign_in_uses_password_manager_hints_and_announces_errors(self):
        response = self.client.get('/accounts/login/')
        invalid = self.client.post('/accounts/login/', {
            'username': 'unknown',
            'password': 'incorrect',
        })

        self.assertContains(response, 'autocomplete="username"')
        self.assertContains(response, 'autocomplete="current-password"')
        self.assertContains(invalid, 'role="alert"')


class StoreUserManagementTests(TestCase):
    """Store admins manage their own store's users from the POS."""
    AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
    databases = {'default', 'archive'}   # the dashboard reads archived sales

    def setUp(self):
        self.store = make_tenant('store-a')
        self.other = make_tenant('store-b')
        self.admin = make_user(self.store, 'boss', role='admin', can_access_user_management=True)
        self.cashier = make_user(self.store, 'till1')
        self.outsider = make_user(self.other, 'elsewhere')
        pos_login(self.client, self.admin)

    def test_page_lists_only_this_stores_users(self):
        resp = self.client.get('/accounts/users/')
        self.assertEqual(resp.status_code, 200)
        names = {p.user.username for p in resp.context['profiles']}
        self.assertEqual(names, {'boss', 'till1'})

    def test_cashier_is_turned_away(self):
        self.client.post('/accounts/logout/')
        pos_login(self.client, self.cashier)
        self.assertRedirects(self.client.get('/accounts/users/'), '/', fetch_redirect_response=False)
        resp = self.client.post('/accounts/users/add/', {'username': 'x'}, **self.AJAX)
        self.assertNotEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username='x').exists())

    def test_admin_adds_a_user_to_their_own_store(self):
        data = self.client.post('/accounts/users/add/', {
            'username': 'till2', 'password': PASSWORD, 'password2': PASSWORD,
            'role': 'cashier', 'is_active': '1',
        }, **self.AJAX).json()
        self.assertTrue(data['success'])
        self.assertEqual(UserProfile.all_objects.get(user__username='till2').tenant_id, self.store.id)
        self.assertEqual(data['user']['edit_url'], f"/accounts/users/{data['user']['pk']}/edit/")

    def test_users_of_another_store_are_out_of_reach(self):
        for action in ('edit', 'password', 'remove'):
            resp = self.client.post(f'/accounts/users/{self.outsider.pk}/{action}/',
                                    {'username': 'hacked', 'role': 'admin'}, **self.AJAX)
            self.assertEqual(resp.status_code, 404, action)
        self.assertTrue(User.objects.filter(username='elsewhere').exists())

    def test_admin_cannot_lock_themselves_out(self):
        data = self.client.post(f'/accounts/users/{self.admin.pk}/edit/', {
            'username': 'boss', 'role': 'cashier', 'is_active': '1',
            'can_access_user_management': '1',
        }, **self.AJAX).json()
        self.assertFalse(data['success'])
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_superuser)

    def test_admin_cannot_remove_themselves(self):
        data = self.client.post(f'/accounts/users/{self.admin.pk}/remove/', **self.AJAX).json()
        self.assertFalse(data['success'])
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_admin_resets_a_cashier_password(self):
        new = 'An0ther-strong-pass'
        data = self.client.post(f'/accounts/users/{self.cashier.pk}/password/',
                                {'new_password1': new, 'new_password2': new}, **self.AJAX).json()
        self.assertTrue(data['success'])
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.check_password(new))

    def test_rail_shows_users_link_to_store_admins(self):
        self.assertContains(self.client.get('/'), 'href="/accounts/users/"')

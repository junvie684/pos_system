"""Every message after an action shows in the one toast at the lower centre."""
import re
from html import unescape

from django.test import TestCase

from tenants.test_utils import make_platform_admin, make_product, make_sale, make_tenant, make_user, pos_login, PASSWORD


def server_messages(html):
    """[(type, text)] queued for the toast on this page."""
    block = re.search(r'<ul id="server-messages" hidden>(.*?)</ul>', html, re.S)
    if not block:
        return []
    return [(kind, unescape(text)) for kind, text in re.findall(r'<li data-type="([a-z]+)">(.*?)</li>', block.group(1), re.S)]


class ServerMessagesUseTheToastTests(TestCase):
    databases = '__all__'   # dashboard and history also read the archive database

    def setUp(self):
        self.tenant = make_tenant('store-a')
        self.manager = make_user(self.tenant, 'manager1', role='manager')
        self.cashier = make_user(self.tenant, 'cashier1')

    def test_message_after_a_redirect_goes_to_the_toast_not_a_banner(self):
        sale = make_sale(self.tenant, self.cashier, make_product(self.tenant))
        pos_login(self.client, self.manager)
        item = sale.items.model.all_objects.get(sale=sale)
        resp = self.client.post(f'/refund/{sale.pk}/', {f'qty_{item.pk}': '1', f'restock_{item.pk}': 'on'},
                                follow=True)
        html = resp.content.decode()
        self.assertEqual(server_messages(html), [(
            'success',
            f'Refunded ₱50.00 for 1 item on {sale} (all returned to stock). The sale is now fully refunded.',
        )])
        self.assertNotIn('class="alert alert-success"', html)
        self.assertNotIn('messages-container', html)

    def test_error_messages_keep_their_type(self):
        pos_login(self.client, self.cashier)
        html = self.client.get('/reports/', follow=True).content.decode()
        self.assertEqual(server_messages(html), [('error', "You don't have access to Reports.")])

    def test_sign_in_page_messages_use_the_toast(self):
        self.tenant.is_active = False
        self.tenant.save()
        html = pos_login(self.client, self.cashier).content.decode()
        self.assertEqual(server_messages(html),
                         [('error', 'This store has been deactivated. Please contact your system provider or system administrator for assistance.')])

    def test_platform_console_messages_use_the_toast(self):
        make_platform_admin('platform')
        self.client.post('/platform/login/', {'username': 'platform', 'password': PASSWORD})
        resp = self.client.post(f'/platform/store/{self.tenant.id}/toggle/', follow=True)
        self.assertTrue(server_messages(resp.content.decode()))

    def test_message_text_is_escaped(self):
        from django.contrib import messages
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.template.loader import render_to_string
        from django.test import RequestFactory
        request = RequestFactory().get('/')
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        messages.error(request, '<img src=x onerror=alert(1)>')
        request.user = self.cashier
        html = render_to_string('accounts/login.html', {'form': None}, request=request)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', html)
        self.assertNotIn('<img src=x', html)


class OneToastTests(TestCase):
    databases = '__all__'   # dashboard and history also read the archive database

    def setUp(self):
        self.tenant = make_tenant('store-a')
        self.admin = make_user(self.tenant, 'admin1', role='admin')
        pos_login(self.client, self.admin)

    def test_every_page_shares_one_toast(self):
        for url in ('/', '/new/', '/history/', '/pending/', '/products/', '/products/categories/',
                    '/customers/', '/accounts/users/'):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertEqual(html.count('function showToast('), 1)    # the shared one only
                self.assertNotIn('rxToast', html)
                self.assertNotIn('id="toast"', html)   # created on demand by the shared script

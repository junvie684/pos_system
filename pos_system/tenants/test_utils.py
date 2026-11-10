"""Shared fixtures for tests. Test-only code; not imported by the app."""
from decimal import Decimal

from django.contrib.auth.models import User

from accounts.models import UserProfile
from products.models import Category, Product
from sales.models import Sale, SaleItem
from tenants.models import Tenant

PASSWORD = 'S3cure-test-pass!'


def make_tenant(slug='store-a'):
    return Tenant.objects.create(name=slug.title(), slug=slug, owner=f'{slug}@example.com')


def make_user(tenant, username, role='cashier', **perms):
    """role: 'admin' (store admin = superuser today), 'manager' (staff), 'cashier'."""
    user = User.objects.create_user(
        username=username,
        password=PASSWORD,
        is_staff=role in ('admin', 'manager'),
        is_superuser=role == 'admin',
    )
    if tenant is not None:
        UserProfile.all_objects.create(user=user, tenant_id=tenant.id, **perms)
    return user


def make_platform_admin(username='platform'):
    return User.objects.create_superuser(username=username, password=PASSWORD, email='')


def make_product(tenant, name='Soap', price='50.00', stock=10, category=None):
    return Product.all_objects.create(
        tenant_id=tenant.id, name=name, price=Decimal(price), stock=stock, category=category,
    )


def make_category(tenant, name='General'):
    return Category.all_objects.create(tenant_id=tenant.id, name=name)


def make_sale(tenant, cashier, product, qty=1, status='completed'):
    sale = Sale.all_objects.create(tenant_id=tenant.id, cashier=cashier, status=status)
    SaleItem.all_objects.create(
        tenant_id=tenant.id, sale=sale, product=product, quantity=qty, unit_price=product.price,
    )
    return sale


def pos_login(client, user):
    resp = client.post('/accounts/login/', {'username': user.username, 'password': PASSWORD})
    return resp


def sale_post(items, status='completed', payment_method='cash', cash_tendered='', change_given='',
              reference_number=''):
    """items: list of (product, qty, unit_price_sent_by_client)."""
    data = {
        'status': status,
        'payment_method': payment_method,
        'cash_tendered': cash_tendered,
        'change_given': change_given,
        'reference_number': reference_number,
        'items-TOTAL_FORMS': str(len(items)),
    }
    for i, (product, qty, price) in enumerate(items):
        data[f'items-{i}-product'] = str(product.pk)
        data[f'items-{i}-quantity'] = str(qty)
        data[f'items-{i}-unit_price'] = str(price)
    return data

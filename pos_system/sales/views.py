from django.contrib import messages
from accounts.decorators import manager_or_admin_required, pos_login_required
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404

from customers.models import Customer
from products.models import Product, Category
from .models import Sale, SaleItem
from django.db import IntegrityError, transaction
from django.db.models import F, DecimalField

from django.db.models import Value, IntegerField, Q as DQ

import json
import uuid
from django.utils import timezone
from django.db.models import Sum, Count
from django.db.models.functions import TruncDate, Coalesce
from datetime import timedelta

from tenants.models import Tenant
from django.http import JsonResponse

from decimal import Decimal, InvalidOperation
import logging

from django.urls import reverse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


# ─── Dashboard ───────────────────────────────────────────────
@pos_login_required
def dashboard(request):

    today = timezone.localdate()
    seven_days_ago = today - timedelta(days=6)

    # ── Today's stats ─────────────────────────────────────────────
    todays_sales = Sale.objects.filter(
        status='completed',
        created_at__date=today
    ).prefetch_related('items')

    total_today = sum(s.total for s in todays_sales)
    avg_sale    = (total_today / len(todays_sales)) if todays_sales else 0

    # ── Recent sales table (last 10 completed today) ───────────────
    recent_sales = Sale.objects.filter(
        status='completed',
        created_at__date=today
    ).order_by('-created_at')[:10]

    # ── Revenue by day (last 7 days) ──────────────────────────────
    daily_revenue = (
        SaleItem.objects
        .filter(
            sale__status='completed',
            sale__created_at__date__gte=seven_days_ago,
        )
        .annotate(day=TruncDate('sale__created_at'))
        .values('day')
        .annotate(revenue=Sum('unit_price') * 1)  # placeholder
        .order_by('day')
    )

    # Build a proper day-by-day revenue using raw aggregation
    from django.db.models import F as Fexpr
    daily_qs = (
        SaleItem.objects
        .filter(sale__status='completed', sale__created_at__date__gte=seven_days_ago)
        .annotate(day=TruncDate('sale__created_at'))
        .values('day')
        .annotate(revenue=Sum(Fexpr('quantity') * Fexpr('unit_price')))
        .annotate(txns=Count('sale', distinct=True))
        .order_by('day')
    )

    # Fill in missing days with 0
    daily_map = {entry['day']: entry for entry in daily_qs}
    chart_days, chart_revenue, chart_txns = [], [], []
    for i in range(7):
        day = seven_days_ago + timedelta(days=i)
        entry = daily_map.get(day)
        chart_days.append(day.strftime('%b %d'))
        chart_revenue.append(float(entry['revenue']) if entry else 0)
        chart_txns.append(entry['txns'] if entry else 0)

    # ── Top 5 products by revenue ─────────────────────────────────
    from django.db.models import F as Fexpr
    top_products = (
        SaleItem.objects
        .filter(sale__status='completed')
        .values('product__name')
        .annotate(revenue=Sum(Fexpr('quantity') * Fexpr('unit_price')))
        .order_by('-revenue')[:5]
    )
    top_product_labels = [p['product__name'] for p in top_products]
    top_product_values = [float(p['revenue']) for p in top_products]

    # ── Top 5 products by units sold ─────────────────────────────
    top_units = (
        SaleItem.objects
        .filter(sale__status='completed')
        .values('product__name')
        .annotate(units=Sum('quantity'))
        .order_by('-units')[:5]
    )
    top_units_labels = [p['product__name'] for p in top_units]
    top_units_values = [p['units'] for p in top_units]

    # ── Low stock products (stock <= 5) ───────────────────────────
    from products.models import Product
    low_stock = (
        Product.objects
        .filter(is_active=True, stock__lte=5)
        .order_by('stock')
    )

    # ── Cashier performance (all time) ────────────────────────────
    cashier_stats = (
        Sale.objects
        .filter(status='completed')
        .values('cashier__username')
        .annotate(
            sales_count=Count('id'),
            revenue=Sum(
                SaleItem.objects.filter(sale=Fexpr('id'))
                .values('sale')
                .annotate(t=Sum(Fexpr('quantity') * Fexpr('unit_price')))
                .values('t')[:1]
            )
        )
    )

    # Simpler cashier stats using Python
    from django.contrib.auth.models import User
    cashier_data = []
    tenant_cashier_ids = (
        Sale.objects
        .filter(status='completed')  # TenantManager scopes this
        .values_list('cashier_id', flat=True)
        .distinct()
    )
    cashiers = User.objects.filter(pk__in=tenant_cashier_ids)
    for cashier in cashiers:
        sales = Sale.objects.filter(status='completed', cashier=cashier).prefetch_related('items')
        rev = sum(s.total for s in sales)
        cashier_data.append({
            'username': cashier.username,
            'sales_count': sales.count(),
            'revenue': rev,
        })
    cashier_data.sort(key=lambda x: x['revenue'], reverse=True)
    max_cashier_revenue = cashier_data[0]['revenue'] if cashier_data else 1

    # ── Sale status counts ────────────────────────────────────────
    status_counts = {
        'completed': Sale.objects.filter(status='completed').count(),
        'refunded':  Sale.objects.filter(status='refunded').count(),
        'pending':   Sale.objects.filter(status='pending').count(),
    }

    # ── Refund rate ───────────────────────────────────────────────
    total_sales_count = status_counts['completed'] + status_counts['refunded']
    refund_rate = round(
        (status_counts['refunded'] / total_sales_count * 100), 1
    ) if total_sales_count else 0

    # ── Low stock count ───────────────────────────────────────────
    low_stock_count = low_stock.count()

    # ── Server-rendered chart data (no JS chart library; works offline) ──
    max_rev = max(chart_revenue) or 1
    days = []
    for i in range(7):
        day = seven_days_ago + timedelta(days=i)
        days.append({
            'label':   day.strftime('%a'),
            'date':    day.strftime('%b %d'),
            'revenue': chart_revenue[i],
            'txns':    chart_txns[i],
            'pct':     round(chart_revenue[i] / max_rev * 100, 1),
            'is_today': day == today,
        })
    yesterday_total = chart_revenue[5]
    week_total = sum(chart_revenue)
    week_txns = sum(chart_txns)
    if yesterday_total:
        today_delta_pct = round((float(total_today) - yesterday_total) / yesterday_total * 100)
    else:
        today_delta_pct = None

    max_top = top_product_values[0] if top_product_values else 1
    top_products_rows = [
        {'name': n, 'value': v, 'pct': round(v / max_top * 100, 1)}
        for n, v in zip(top_product_labels, top_product_values)
    ]
    max_units = top_units_values[0] if top_units_values else 1
    top_units_rows = [
        {'name': n, 'value': v, 'pct': round(v / max_units * 100, 1)}
        for n, v in zip(top_units_labels, top_units_values)
    ]
    status_total = sum(status_counts.values()) or 1
    status_pct = {k: round(v / status_total * 100, 1) for k, v in status_counts.items()}

    return render(request, 'sales/dashboard.html', {
        # Today
        'total_today':        total_today,
        'avg_sale':           avg_sale,
        'recent_sales':       recent_sales,
        'sales_count_today':  len(todays_sales),

        # Refund & stock summary
        'refund_rate':        refund_rate,
        'total_sales_count':  total_sales_count,
        'low_stock_count':    low_stock_count,

        # Charts (JSON for JS)
        'chart_days':         json.dumps(chart_days),
        'chart_revenue':      json.dumps(chart_revenue),
        'chart_txns':         json.dumps(chart_txns),
        'top_product_labels': json.dumps(top_product_labels),
        'top_product_values': json.dumps(top_product_values),
        'top_units_labels':   json.dumps(top_units_labels),
        'top_units_values':   json.dumps(top_units_values),

        # Server-rendered charts
        'days':               days,
        'yesterday_total':    yesterday_total,
        'today_delta_pct':    today_delta_pct,
        'today_delta_abs':    abs(today_delta_pct) if today_delta_pct is not None else None,
        'week_total':         week_total,
        'week_txns':          week_txns,
        'top_products_rows':  top_products_rows,
        'top_units_rows':     top_units_rows,
        'status_pct':         status_pct,

        # Tables/lists
        'low_stock':          low_stock[:8],
        'cashier_data':       cashier_data,
        'max_cashier_revenue': max_cashier_revenue,
        'status_counts':      status_counts,
    })

def _cashier_today(user):
    """Completed sales rung up by this cashier today: (count, total)."""
    sales = Sale.objects.filter(cashier=user, status='completed', created_at__date=timezone.localdate())
    count = sales.count()
    total = SaleItem.objects.filter(sale__in=sales).aggregate(
        t=Coalesce(Sum(F('quantity') * F('unit_price')), Value(Decimal('0')), output_field=DecimalField())
    )['t']
    return {'today_count': count, 'today_total': total}

# ─── Checkout (shared by create_sale and resume_sale) ────────
ALLOWED_SALE_STATUSES = ('completed', 'pending')
PAYMENT_METHOD_CODES = {code for code, _ in Sale.PAYMENT_METHODS}
# Mirrors EWALLET_METHODS in templates/sales/create_sale.html
REFERENCE_REQUIRED_METHODS = {'gcash', 'maya', 'grabpay', 'bank_transfer'}
MAX_AMOUNT = Decimal('99999999.99')  # DecimalField(max_digits=10, decimal_places=2)
CENT = Decimal('0.01')
PRESERVED_KEYS = ('cart', 'customer', 'cash_tendered', 'payment_method', 'reference_number')


class CheckoutError(Exception):
    """A checkout problem to show the cashier. The sale transaction is rolled back."""


def _pos_screen_context():
    products = (
        Product.objects
        .filter(is_active=True)
        .select_related('category')
        .annotate(
            total_sold=Coalesce(
                Sum('saleitem__quantity', filter=DQ(saleitem__sale__status='completed')),
                Value(0), output_field=IntegerField()
            )
        )
        .order_by('-total_sold')[:24]
    )
    return {
        'products': products,
        'customers': Customer.objects.all(),
        'categories': Category.objects.all(),
        # Fresh per screen load; the page reloads after every finished sale.
        'idempotency_key': str(uuid.uuid4()),
        'product_api_url': reverse('sales:product_lookup'),
    }


def _pop_preserved(session):
    """Cart + form values stashed by a failed checkout, consumed once."""
    data = {k: session.pop(f'preserved_{k}', None) for k in PRESERVED_KEYS}
    cart = data.pop('cart')
    return {
        # Raw list; the template emits it with |json_script (never |safe),
        # so a product name can't close the <script> block.
        'preserved_cart': cart or None,
        **{f'preserved_{k}': v for k, v in data.items()},
    }


def _parse_lines(post):
    """
    [(product_id, qty)] from the cart's items-N-* fields. Client prices are ignored.
    Repeated products are merged into one line so stock is checked against the
    real total quantity (in first-seen order).
    """
    try:
        total_forms = min(int(post.get('items-TOTAL_FORMS', 0)), 1000)
    except ValueError:
        return []
    merged = {}
    for i in range(total_forms):
        try:
            product_id = int(post.get(f'items-{i}-product', ''))
            qty = int(post.get(f'items-{i}-quantity', ''))
        except ValueError:
            continue
        if qty > 0:
            merged[product_id] = merged.get(product_id, 0) + qty
    return list(merged.items())


def _settle_payment(sale, status, method, tendered_raw, reference, total):
    """Set cash/change/reference from server-side numbers only."""
    if status != 'completed':
        sale.cash_tendered = sale.change_given = sale.reference_number = None
        return

    if method == 'cash':
        if not tendered_raw:
            tendered = total  # blank = customer paid the exact amount
        else:
            try:
                tendered = Decimal(tendered_raw).quantize(CENT)
            except InvalidOperation:
                raise CheckoutError('Enter a valid cash amount.')
            if tendered > MAX_AMOUNT:
                raise CheckoutError('Enter a valid cash amount.')
        if tendered < total:
            raise CheckoutError('Cash received is less than the total.')
        sale.cash_tendered = tendered
        sale.change_given = tendered - total
        sale.reference_number = reference or None
    else:
        if method in REFERENCE_REQUIRED_METHODS and not reference:
            raise CheckoutError('Enter the reference number to continue.')
        sale.cash_tendered = None
        sale.change_given = None
        sale.reference_number = reference or None


def _is_ajax(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _parse_idempotency_key(post):
    try:
        return uuid.UUID(post.get('idempotency_key', ''))
    except ValueError:
        return None


def _sale_done_response(request, sale, message=None):
    """Where the POS goes after a sale is recorded (or found already recorded)."""
    if sale.status == 'pending':
        if _is_ajax(request):
            return JsonResponse({'success': True, 'redirect': reverse('sales:pending_sales')})
        if message:
            messages.success(request, message)
        return redirect('sales:pending_sales')

    if _is_ajax(request):
        return JsonResponse({'success': True, 'sale_id': sale.pk})
    if message:
        messages.success(request, message)
    return redirect('sales:receipt', sale_id=sale.pk)


def _replayed_checkout(request):
    """
    If this checkout's key already produced a sale (double-click, or a retry
    after the first response was lost), answer as the first request did
    instead of recording the sale again. Returns None for a new checkout.
    """
    key = _parse_idempotency_key(request.POST)
    if key is None:
        return None
    sale = Sale.objects.filter(idempotency_key=key).first()
    return _sale_done_response(request, sale) if sale else None


def _checkout(request, pending_sale=None):
    """
    Validate and record a sale (new, or completing/re-holding a pending one).
    Prices, totals and change are always computed on the server.
    """
    replay = _replayed_checkout(request)
    if replay:
        return replay

    is_ajax = _is_ajax(request)
    idempotency_key = _parse_idempotency_key(request.POST)
    retry_url = (reverse('sales:resume_sale', args=[pending_sale.pk]) if pending_sale
                 else reverse('sales:create_sale'))

    status = request.POST.get('status', 'completed')
    payment_method = request.POST.get('payment_method', 'cash')
    tendered_raw = (request.POST.get('cash_tendered') or '').strip()
    reference = (request.POST.get('reference_number') or '').strip()[:100]
    customer_id = request.POST.get('customer') or None
    form_state = {
        'customer': customer_id,
        'cash_tendered': tendered_raw or None,
        'payment_method': payment_method,
        'reference_number': reference or None,
    }

    def fail(message, cart=()):
        if message:
            messages.error(request, message)
        request.session['preserved_cart'] = list(cart)
        for key, value in form_state.items():
            request.session[f'preserved_{key}'] = value
        if is_ajax:
            return JsonResponse({'success': False, 'reload': True})
        return redirect(retry_url)

    if status not in ALLOWED_SALE_STATUSES or payment_method not in PAYMENT_METHOD_CODES:
        return fail('Invalid sale request. Please try again.')

    lines = _parse_lines(request.POST)
    if not lines:
        return fail('No valid items in the sale.')

    customer = None
    if customer_id and str(customer_id).isdigit():
        customer = Customer.objects.filter(pk=customer_id).first()

    # Pre-check stock so the cashier sees every shortfall at once.
    # (Re-enforced under row locks + the stock >= 0 DB constraint below.)
    products = Product.objects.filter(pk__in={pid for pid, _ in lines}, is_active=True).in_bulk()
    cart, stock_errors = [], []
    for pid, qty in lines:
        product = products.get(pid)
        if product is None:
            continue
        short = status == 'completed' and product.stock < qty
        if short:
            stock_errors.append((product.name, qty, product.stock))
        cart.append({
            'product_id': str(pid),
            'name': product.name,
            'quantity': qty,
            'unit_price': float(product.price),  # display only
            'stock': product.stock,
            'has_error': short,
        })

    if stock_errors:
        if not is_ajax:
            for name, requested, available in stock_errors:
                messages.error(
                    request,
                    f'"{name}" — requested {requested}, only {available} in stock. '
                    f'Reduce quantity or remove from cart.'
                )
        return fail(None, cart)

    try:
        with transaction.atomic():
            if pending_sale is None:
                sale = Sale(cashier=request.user)
            else:
                # Lock the pending sale so two terminals can't complete it twice.
                sale = Sale.objects.select_for_update().get(pk=pending_sale.pk, status='pending')
                sale.items.all().delete()  # pending sales never deducted stock
                if status == 'completed':
                    sale.created_at = timezone.now()

            sale.customer = customer
            sale.status = status
            sale.payment_method = payment_method
            if idempotency_key:
                sale.idempotency_key = idempotency_key  # unique: a concurrent duplicate fails here
            sale.save()

            total = Decimal('0.00')
            for pid, qty in lines:
                try:
                    product = Product.objects.select_for_update().get(pk=pid, is_active=True)
                except Product.DoesNotExist:
                    raise CheckoutError('A product in the sale no longer exists or is inactive.')
                if status == 'completed':
                    Product.objects.filter(pk=pid).update(stock=F('stock') - qty)
                SaleItem.objects.create(sale=sale, product=product, quantity=qty, unit_price=product.price)
                total += product.price * qty

            _settle_payment(sale, status, payment_method, tendered_raw, reference, total)
            sale.save()

    except CheckoutError as exc:
        return fail(str(exc), cart)
    except Sale.DoesNotExist:
        messages.error(request, f'Sale #{pending_sale.pk} is no longer pending.')
        return redirect('sales:pending_sales')
    except IntegrityError:
        # A simultaneous duplicate of this checkout won the race: reply with its sale.
        replay = _replayed_checkout(request)
        if replay:
            return replay
        logger.exception('Checkout failed (pending_sale=%s)', getattr(pending_sale, 'pk', None))
        return fail('Sale could not be completed. Please try again.', cart)
    except Exception:
        logger.exception('Checkout failed (pending_sale=%s)', getattr(pending_sale, 'pk', None))
        return fail('Sale could not be completed. Please try again.', cart)

    if status == 'pending':
        verb = 'updated and kept on hold' if pending_sale else 'saved as pending'
        return _sale_done_response(request, sale, f'Sale #{sale.pk} {verb}.')
    return _sale_done_response(request, sale, f'Sale #{sale.pk} completed successfully.')


# ─── Product lookup for the POS screen ───────────────────────
PRODUCT_SEARCH_LIMIT = 20


def _product_payload(product):
    return {
        'id': product.pk,
        'name': product.name,
        'price': str(product.price),
        'stock': product.stock,
        'barcode': product.barcode or '',
        'category': product.category.name if product.category else '',
        'image': product.image.url if product.image else '',
    }


@pos_login_required
@require_GET
def product_lookup(request):
    """
    The POS grid only renders the best sellers, so scans and searches that
    miss it ask here. `?barcode=` is an exact match; `?q=` searches name,
    barcode and category. Active products of the current store only.
    """
    barcode = request.GET.get('barcode', '').strip()
    query = request.GET.get('q', '').strip()
    products = Product.objects.filter(is_active=True).select_related('category')

    if barcode:
        products = products.filter(barcode=barcode)[:1]
    elif query:
        products = products.filter(
            Q(name__icontains=query) | Q(barcode__icontains=query) | Q(category__name__icontains=query)
        ).order_by('name')[:PRODUCT_SEARCH_LIMIT]
    else:
        products = []

    return JsonResponse({'products': [_product_payload(p) for p in products]})


# ─── Create Sale (POS) ───────────────────────────────────────
@pos_login_required
def create_sale(request):
    if request.method == 'POST':
        return _checkout(request)

    return render(request, 'sales/create_sale.html', {
        **_pos_screen_context(),
        **_pop_preserved(request.session),
        **_cashier_today(request.user),
    })

# ─── Pending Sales ─────────────────────────────────────────────

@pos_login_required
def pending_sales(request):
    """List all pending sales (admin sees all, cashier sees only theirs)"""
    if request.user.is_superuser or request.user.profile.can_access_user_management:
        pending = Sale.objects.filter(status='pending').order_by('-created_at')
    else:
        pending = Sale.objects.filter(status='pending', cashier=request.user).order_by('-created_at')

    return render(request, 'sales/pending_sales.html', {'pending_sales': pending})


@pos_login_required
def resume_sale(request, pk):
    sale = get_object_or_404(Sale, pk=pk)

    # A retried completion arrives after the sale is no longer pending.
    if request.method == 'POST':
        replay = _replayed_checkout(request)
        if replay:
            return replay

    if sale.status != 'pending':
        messages.error(request, f'Sale #{pk} is no longer pending.')
        return redirect('sales:pending_sales')

    if not (
            request.user.is_superuser or request.user.profile.can_access_user_management or sale.cashier == request.user):
        messages.error(request, 'Permission denied.')
        return redirect('sales:pending_sales')

    if request.method == 'POST':
        return _checkout(request, pending_sale=sale)

    # Show what will actually be charged: checkout re-prices from the product,
    # so the cart must use today's price, not the price when the sale was held.
    pending_cart, pending_removed = [], []
    for item in sale.items.select_related('product'):
        product = item.product
        if not product.is_active:
            pending_removed.append(product.name)
            continue
        pending_cart.append({
            'product_id': str(product.pk),
            'name': product.name,
            'unit_price': float(product.price),  # display only
            'quantity': item.quantity,
            'stock': product.stock,
            'price_changed': product.price != item.unit_price,
        })

    return render(request, 'sales/create_sale.html', {
        **_pos_screen_context(),
        'pending_sale': sale,
        'pending_cart': pending_cart,
        'pending_removed': pending_removed,
        **_pop_preserved(request.session),
        **_cashier_today(request.user),
    })


@pos_login_required
def delete_pending(request, pk):
    """Delete a pending sale"""
    sale = get_object_or_404(Sale, pk=pk, status='pending')

    if not (
            request.user.is_superuser or request.user.profile.can_access_user_management or sale.cashier == request.user):
        messages.error(request, 'Permission denied.')
        return redirect('sales:pending_sales')

    if request.method == 'POST':
        sale.delete()
        messages.success(request, 'Pending sale deleted.')
        return redirect('sales:pending_sales')

    return render(request, 'sales/delete_pending.html', {'sale': sale})

# ─── Sale History ─────────────────────────────────────────────
from django.core.paginator import Paginator

@pos_login_required
def sale_history(request):
    sales = Sale.objects.filter(status__in=['completed', 'refunded']).order_by('-created_at')

    # Search filter
    query = request.GET.get('q', '')
    if query:
        sales = sales.filter(
            Q(customer__name__icontains=query) |
            Q(cashier__username__icontains=query) |
            Q(pk__icontains=query) |
            Q(status__icontains=query)
        )

    # Date filter (shortcuts fill the range)
    date_from = request.GET.get('date_from', '')
    date_to   = request.GET.get('date_to', '')
    preset    = request.GET.get('range', '')
    today = timezone.localdate()
    presets = {
        'today':     (today, today),
        'yesterday': (today - timedelta(days=1), today - timedelta(days=1)),
        'week':      (today - timedelta(days=today.weekday()), today),
        'month':     (today.replace(day=1), today),
    }
    if preset in presets:
        start, end = presets[preset]
        date_from, date_to = start.isoformat(), end.isoformat()
    if date_from:
        sales = sales.filter(created_at__date__gte=date_from)
    if date_to:
        sales = sales.filter(created_at__date__lte=date_to)

    from datetime import date as _date
    def _fmt(d):
        try:
            return _date.fromisoformat(d)
        except (TypeError, ValueError):
            return None
    d_from, d_to = _fmt(date_from), _fmt(date_to)
    preset_names = {'today': 'Today', 'yesterday': 'Yesterday', 'week': 'This week', 'month': 'This month'}
    if d_from and d_to and d_from == d_to:
        span = f"{d_from:%b} {d_from.day}, {d_from.year}"
    elif d_from and d_to:
        span = (f"{d_from:%b} {d_from.day} – {d_to.day}, {d_to.year}" if (d_from.year, d_from.month) == (d_to.year, d_to.month)
                else f"{d_from:%b} {d_from.day}, {d_from.year} – {d_to:%b} {d_to.day}, {d_to.year}")
    elif d_from:
        span = f"From {d_from:%b} {d_from.day}, {d_from.year}"
    elif d_to:
        span = f"Until {d_to:%b} {d_to.day}, {d_to.year}"
    else:
        span = 'All dates'
    scope_label = f"{preset_names[preset]} · {span}" if preset in preset_names else span

    completed = sales.filter(status='completed')
    filtered_total = SaleItem.objects.filter(sale__in=completed).aggregate(
        t=Coalesce(Sum(F('quantity') * F('unit_price')), Value(Decimal('0')), output_field=DecimalField())
    )['t']
    filtered_count = completed.count()
    refunded_count = sales.filter(status='refunded').count()

    paginator = Paginator(sales.prefetch_related('items__product').select_related('customer', 'cashier'), 12)
    page      = request.GET.get('page')
    sales     = paginator.get_page(page)

    return render(request, 'sales/history.html', {
        'sales':          sales,
        'query':          query,
        'date_from':      date_from,
        'date_to':        date_to,
        'preset':         preset if preset in presets else '',
        'filtered_total': filtered_total,
        'filtered_count': filtered_count,
        'refunded_count': refunded_count,
        'scope_label':    scope_label,
    })

# ─── Refund/Void ─────────────────────────────────────────────

@manager_or_admin_required
def refund_sale(request, pk):
    sale = get_object_or_404(Sale, pk=pk)

    if sale.status != 'completed':
        # Pending sales never deducted stock; refunded ones already restored it.
        messages.error(request, f'Sale #{sale.pk} is {sale.get_status_display().lower()} and cannot be refunded.')
        return redirect('sales:sale_history')

    if request.method == 'POST':
        with transaction.atomic():
            # Conditional update: only one request can flip completed -> refunded,
            # so stock is restored exactly once even on double-clicks or races.
            claimed = Sale.objects.filter(pk=sale.pk, status='completed').update(
                status='refunded', refunded_by=request.user, refunded_at=timezone.now(),
            )
            if claimed:
                for item in SaleItem.objects.filter(sale_id=sale.pk):
                    Product.objects.filter(pk=item.product_id).update(stock=F('stock') + item.quantity)

        if not claimed:
            messages.error(request, f'Sale #{sale.pk} was already refunded.')
        else:
            messages.success(request, f'Sale #{sale.pk} has been refunded and stock restored.')
        return redirect('sales:sale_history')

    return render(request, 'sales/refund_confirm.html', {'sale': sale})


# ─── Receipt ─────────────────────────────────────────────

@pos_login_required
def receipt(request, sale_id):
    sale = get_object_or_404(Sale, pk=sale_id)

    try:
        tenant_id = request.session.get('tenant_id')
        tenant = Tenant.objects.get(id=tenant_id)
    except Exception:
        return redirect('/accounts/login/')

    vatable_sale = sale.total / Decimal('1.12')
    vat_amount = sale.total - vatable_sale

    return render(request, 'sales/receipt.html', {
        'sale': sale,
        'tenant': tenant,
        'vatable_sale': vatable_sale,
        'vat_amount': vat_amount,
    })
import re
from django.contrib import messages
from accounts.decorators import (
    dashboard_access_required, feature_required, manager_or_admin_required, pos_login_required,
)
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
from django.utils.timesince import timesince
from django.db.models import Sum, Count
from django.contrib.auth.models import User
from django.db.models.functions import TruncDate, Coalesce, Concat
from datetime import timedelta

from tenants.models import Tenant
from django.http import JsonResponse

from decimal import Decimal, InvalidOperation
import logging

from django.urls import reverse
from django.views.decorators.http import require_GET


logger = logging.getLogger(__name__)


# ─── Dashboard ───────────────────────────────────────────────
def _print_context(request, title, period):
    """Header and file name for a Dashboard tab's PDF export (see partials/dashboard_print.html)."""
    store = Tenant.objects.filter(id=request.session.get('tenant_id')).values_list('name', flat=True).first()
    name = f"{store or 'POS'} - Dashboard {title} - {timezone.localdate():%Y-%m-%d}"
    return {
        'print_title': title,
        'print_period': period,
        'print_landscape': True,
        'print_filename_json': json.dumps(re.sub(r'[\\/:*?"<>|]', '', name)),
    }


def _custom_range(request, today):
    """(start, end) from ?from=&to= (either order, end capped at today), or None
    with an error message if they aren't two valid dates."""
    from datetime import date
    try:
        start = date.fromisoformat(request.GET.get('from', ''))
        end = date.fromisoformat(request.GET.get('to', ''))
    except ValueError:
        start = end = None
    if start and end:
        start, end = min(start, end), min(max(start, end), today)
        if start <= end:
            return start, end
    messages.error(request, 'Pick a start and end date for the custom range.')
    return None


@dashboard_access_required
def dashboard(request):
    """Tiles: period summaries across the top; the selected tile's products
    (or sale lines) underneath."""
    from reports.tiles import (
        DEFAULT_PRESET, PRESETS, build_periods, build_tiles, date_label, group_rows,
        order_items, product_rows,
    )

    today = timezone.localdate()
    preset = request.GET.get('preset', DEFAULT_PRESET)
    custom, custom_from, custom_to = None, request.GET.get('from', ''), request.GET.get('to', '')
    if preset == 'custom':
        custom = _custom_range(request, today)
        if custom is None:
            preset = DEFAULT_PRESET
    elif preset not in PRESETS:
        preset = DEFAULT_PRESET

    periods = build_periods(preset, today, custom)
    tiles, archive_unavailable = build_tiles(periods, today)

    try:
        selected = int(request.GET.get('tile', 0))
    except ValueError:
        selected = 0
    if not 0 <= selected < len(periods):
        selected = 0
    period = periods[selected]
    end = min(period.end, today)

    view = 'items' if request.GET.get('view') == 'items' else 'products'
    group = 'none' if request.GET.get('group') == 'none' else 'category'

    ctx = {
        'tiles': tiles,
        'selected': selected,
        'selected_title': period.title,
        'selected_dates': date_label(period.start, end),
        'presets': PRESETS.items(),
        'preset': preset,
        'custom_from': custom[0].isoformat() if custom else custom_from,
        'custom_to': custom[1].isoformat() if custom else custom_to,
        'today': today,
        'view': view,
        'group': group,
    }
    if view == 'items':
        ctx['lines'], ctx['line_total'] = order_items(period.start, end)
    else:
        rows, products_unavailable = product_rows(period.start, end)
        archive_unavailable = archive_unavailable or products_unavailable
        ctx['rows'] = rows
        ctx['groups'] = group_rows(rows) if group == 'category' else None
        ctx['totals'] = {
            'units': sum(r['units'] for r in rows),
            'refund_units': sum(r['refund_units'] for r in rows),
            'sales': sum((r['sales'] for r in rows), Decimal('0')),
            'refund_cost': sum((r['refund_cost'] for r in rows), Decimal('0')),
            'net': sum((r['net'] for r in rows), Decimal('0')),
        }
    ctx['archive_unavailable'] = archive_unavailable
    preset_label = PRESETS.get(preset) or f"Custom range {date_label(*custom)}"
    ctx.update(_print_context(
        request, 'Tiles',
        f"{preset_label} · table: {period.title}, {ctx['selected_dates']} · "
        f"{'Order items' if view == 'items' else 'Products'}",
    ))

    # Links keep the period choice; a tile or view switch only changes its own part.
    base = {'preset': preset}
    if preset == 'custom':
        base.update({'from': ctx['custom_from'], 'to': ctx['custom_to']})
    from urllib.parse import urlencode
    ctx['qs_tile'] = urlencode({**base, 'view': view, 'group': group})
    ctx['qs_view'] = urlencode({**base, 'tile': selected, 'group': group})
    ctx['qs_group'] = urlencode({**base, 'tile': selected, 'view': view})
    return render(request, 'sales/dashboard.html', ctx)


# ─── Dashboard: Chart tab ────────────────────────────────────
@dashboard_access_required
def charts(request):
    """One measure over time, a summary beside it, and breakdowns of the period."""
    from reports import charts as rc
    from reports.pnl import fmt
    from reports.tiles import date_label

    today = timezone.localdate()
    range_key = request.GET.get('range', rc.DEFAULT_RANGE)
    custom = None
    if range_key == 'custom':
        custom = _custom_range(request, today)
        if custom is None:
            range_key = rc.DEFAULT_RANGE
    elif range_key not in rc.RANGES:
        range_key = rc.DEFAULT_RANGE
    metric = request.GET.get('metric', rc.DEFAULT_METRIC)
    if metric not in rc.METRICS:
        metric = rc.DEFAULT_METRIC
    metric_label, metric_kind = rc.METRICS[metric]

    start, end, step = rc.range_dates(range_key, today, custom)
    series = rc.time_series(start, end, step, metric, today)
    parts = rc.breakdowns(start, end)

    for b in series['buckets']:
        b['text'] = fmt(b['value'], metric_kind)
    for t in series['ticks']:
        t['text'] = rc.tick_text(t['value'], metric_kind)

    latest = next((b for b in reversed(series['buckets']) if b['is_current']), series['buckets'][-1])
    summaries = [
        {'key': 'latest', 'label': latest['full'], 'rows': rc.summary(latest['fig'])},
        {'key': 'period', 'label': date_label(start, end),
         'rows': rc.summary(series['total'])},
    ]
    for sm in summaries:
        for r in sm['rows']:
            r['text'] = fmt(r['value'], r['kind'])

    range_label = rc.RANGES.get(range_key) or f"Custom range {date_label(start, end)}, by {step}"
    print_ctx = _print_context(request, 'Chart', f"{range_label} · chart: {metric_label}")

    base = {'range': range_key}
    if custom:
        base.update({'from': custom[0].isoformat(), 'to': custom[1].isoformat()})
    from urllib.parse import urlencode
    return render(request, 'sales/charts.html', {
        'ranges': rc.RANGES.items(),
        'range_key': range_key,
        'custom_from': custom[0].isoformat() if custom else request.GET.get('from', ''),
        'custom_to': custom[1].isoformat() if custom else request.GET.get('to', ''),
        'today': today,
        'metrics': [(k, v[0]) for k, v in rc.METRICS.items()],
        'metric': metric,
        'metric_label': metric_label,
        'step': step,
        'qs_metric': urlencode(base),
        'series': series,
        'summaries': summaries,
        'payments': rc.bars(series['payments'])[0],
        **{k: v for k, v in parts.items() if k != 'archive_unavailable'},
        'archive_unavailable': series['archive_unavailable'] or parts['archive_unavailable'],
        **print_ctx,
    })


# ─── Dashboard: P&L tab ──────────────────────────────────────
@feature_required('can_access_reports')
def pnl(request):
    import csv
    from django.http import HttpResponse
    from reports.pnl import DEFAULT_PERIOD, PERIODS, build_pnl, fmt

    try:
        months = int(request.GET.get('months', DEFAULT_PERIOD))
    except ValueError:
        months = DEFAULT_PERIOD
    if months not in PERIODS:
        months = DEFAULT_PERIOD

    today = timezone.localdate()
    table = build_pnl(today, months)
    for row in table['rows']:
        for r in (row, *row['children']):
            r['cells'] = [fmt(v, r['kind']) for v in r['values']]
            r['total_text'] = fmt(r['total'], r['kind'])

    if request.GET.get('format') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="pnl-{today:%Y-%m-%d}.csv"'
        response.write('﻿')  # so Excel reads the peso sign
        writer = csv.writer(response)
        writer.writerow(['Parameter', *(c['label'] for c in table['columns']), 'Total'])
        for row in table['rows']:
            for r, prefix in ((row, ''), *((c, '  ') for c in row['children'])):
                writer.writerow([prefix + r['label'], *r['cells'], r['total_text']])
        return response

    return render(request, 'sales/pnl.html', {
        **table,
        'months': months,
        'periods': PERIODS,
        **_print_context(request, 'P&L', f'Last {months} months, by month'),
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


TOP_SELLERS = 20


def _pos_screen_context():
    """Every active product for the POS tiles: the top sellers first (most sold
    first, each tagged with its rank), then everything else A to Z."""
    products = list(
        Product.objects
        .filter(is_active=True)
        .select_related('category')
        .annotate(
            total_sold=Coalesce(
                Sum('saleitem__quantity', filter=DQ(saleitem__sale__status='completed')),
                Value(0), output_field=IntegerField()
            )
        )
        .order_by('name')
    )
    sold = sorted((p for p in products if p.total_sold > 0), key=lambda p: -p.total_sold)
    top = sold[:TOP_SELLERS]
    for rank, product in enumerate(top, start=1):
        product.best_rank = rank
    top_ids = {p.pk for p in top}
    products = top + [p for p in products if p.pk not in top_ids]
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
            if not tendered.is_finite() or tendered > MAX_AMOUNT:   # "NaN" parses and quantizes
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
                # Price and cost as they stand now; a held sale gets fresh ones when completed.
                SaleItem.objects.create(sale=sale, product=product, quantity=qty,
                                        unit_price=product.price, unit_cost=product.cost)
                total += product.price * qty

            _settle_payment(sale, status, payment_method, tendered_raw, reference, total)
            if status == 'completed':
                sale.assign_or_number()
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
    return _sale_done_response(request, sale, f'Sale {sale.or_display} completed successfully.')


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
    }


@pos_login_required
@require_GET
def product_lookup(request):
    """
    The POS grid renders every active product; scans and searches that miss
    it (e.g. a product added since the page loaded) ask here. `?barcode=` is an exact match; `?q=` searches name,
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

    pending = list(pending.select_related('customer', 'cashier').prefetch_related('items__product'))
    for sale in pending:
        sale.held_for = timesince(sale.created_at, depth=1)  # "3 hours", not "3 hours, 10 minutes"
    return render(request, 'sales/pending_sales.html', {
        'pending_sales': pending,
        'held_total': sum((sale.total for sale in pending), Decimal('0')),
    })


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

from archive.history import TimelineList, archived_history, archived_summary

def _or_number_q(query):
    """Match an OR number typed as "OR-000012", "or12" or "12"."""
    digits = re.sub(r'^\s*or[\s#-]*', '', query, flags=re.I).strip()
    return Q(or_number=int(digits)) if digits.isdigit() else Q(pk__in=[])


@pos_login_required
def sale_history(request):
    sales = Sale.objects.filter(status__in=['completed', 'refunded']).order_by('-created_at')

    # Search filter
    query = request.GET.get('q', '')
    if query:
        sales = sales.annotate(
            cashier_full_name=Concat('cashier__first_name', Value(' '), 'cashier__last_name'),
        ).filter(
            Q(customer__name__icontains=query) |
            Q(cashier__username__icontains=query) |
            Q(cashier_full_name__icontains=query) |
            Q(pk__icontains=query) |
            Q(status__icontains=query) |
            _or_number_q(query)
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
    # Less money already handed back on sales that are only partly refunded.
    from .models import RefundItem
    filtered_total -= RefundItem.objects.filter(refund__sale__in=completed).aggregate(
        t=Coalesce(Sum(F('quantity') * F('unit_price')), Value(Decimal('0')), output_field=DecimalField())
    )['t']
    filtered_count = completed.count()
    refunded_count = sales.filter(status='refunded').count()

    # Sales past the retention period live in the archive database; they
    # follow the main-database sales (they are always older).
    archived = archived_history(sales, query, d_from, d_to)
    arch_total, arch_count, arch_refunded = archived_summary(archived)
    filtered_total += arch_total
    filtered_count += arch_count
    refunded_count += arch_refunded

    timeline = TimelineList(
        sales.order_by('-created_at', '-pk').prefetch_related('items__product', 'refunds__items').select_related('customer', 'cashier'),
        archived,
    )
    sales = Paginator(timeline, 25).get_page(request.GET.get('page'))

    # Archived copies only hold the username: look up this page's full names at once.
    archived_rows = [s for s in sales.object_list if getattr(s, 'is_archived', False)]
    if archived_rows:
        names = {u.pk: u.get_full_name() for u in
                 User.objects.filter(pk__in={s.cashier_id for s in archived_rows if s.cashier_id})}
        for s in archived_rows:
            s._cashier_display = names.get(s.cashier_id) or s.cashier_name

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
        'archive_unavailable': archived is None,
    })

# ─── Refund/Void ─────────────────────────────────────────────

@manager_or_admin_required
def refund_sale(request, pk):
    """Refund some or all of a sale's items. Each line says how many to return
    and whether they go back into stock; the sale turns 'refunded' once every
    item has been returned. A sale can be refunded in parts, on different days."""
    from .models import Refund, RefundItem

    sale = get_object_or_404(Sale, pk=pk)
    if sale.status != 'completed':
        # Pending sales were never paid; fully refunded ones have nothing left.
        messages.error(request, f'Sale {sale} is {sale.get_status_display().lower()} and cannot be refunded.')
        return redirect('sales:sale_history')

    def lines_for(sale_id):
        done = dict(
            RefundItem.objects.filter(sale_item__sale_id=sale_id).order_by()
            .values('sale_item_id').annotate(q=Sum('quantity')).values_list('sale_item_id', 'q')
        )
        return [
            {'item': item, 'refunded': done.get(item.pk, 0), 'left': item.quantity - done.get(item.pk, 0)}
            for item in SaleItem.objects.filter(sale_id=sale_id).select_related('product').order_by('pk')
        ]

    if request.method == 'POST':
        error = None
        with transaction.atomic():
            # Lock the sale so two refunds of it can't both use the same items.
            locked = Sale.objects.select_for_update().filter(pk=sale.pk, status='completed').first()
            if locked is None:
                error = f'Sale {sale} was already fully refunded.'
            else:
                lines = lines_for(sale.pk)
                picked = []
                for line in lines:
                    raw = request.POST.get(f'qty_{line["item"].pk}', '0').strip() or '0'
                    try:
                        qty = int(raw)
                    except ValueError:
                        qty = -1
                    if qty < 0 or qty > line['left']:
                        error = (f'{line["item"].product.name}: enter 0 to {line["left"]} '
                                 f'(only {line["left"]} left to refund).')
                        break
                    if qty:
                        picked.append((line, qty, request.POST.get(f'restock_{line["item"].pk}') == 'on'))
                if not error and not picked:
                    error = 'Enter how many of at least one item to refund.'

                if not error:
                    now = timezone.now()
                    refund = Refund.objects.create(sale=locked, refunded_by=request.user, refunded_at=now)
                    RefundItem.objects.bulk_create([
                        RefundItem(tenant_id=locked.tenant_id, refund=refund, sale_item=line['item'],
                                   quantity=qty, unit_price=line['item'].unit_price, restocked=restock)
                        for line, qty, restock in picked
                    ])
                    for line, qty, restock in picked:
                        if restock:
                            Product.objects.filter(pk=line['item'].product_id).update(stock=F('stock') + qty)
                    picked_qty = {line['item'].pk: qty for line, qty, _ in picked}
                    all_back = all(line['left'] == picked_qty.get(line['item'].pk, 0) for line in lines)
                    if all_back:
                        Sale.objects.filter(pk=locked.pk).update(
                            status='refunded', refunded_by=request.user, refunded_at=now,
                        )
                    amount = sum((line['item'].unit_price * qty for line, qty, _ in picked), Decimal('0'))
                    units = sum(qty for _, qty, _ in picked)
                    restocked = sum(qty for _, qty, r in picked if r)

        if error:
            messages.error(request, error)
            return redirect('sales:refund_sale', pk=sale.pk)
        stock_note = ('all returned to stock' if restocked == units
                      else 'none returned to stock' if not restocked
                      else f'{restocked} returned to stock')
        messages.success(
            request,
            f'Refunded ₱{amount:,.2f} for {units} item{"s" if units != 1 else ""} '
            f'on {sale} ({stock_note}).{" The sale is now fully refunded." if all_back else ""}',
        )
        return redirect('sales:sale_history')

    lines = lines_for(sale.pk)
    refunds = sale.refunds.select_related('refunded_by').prefetch_related('items__sale_item__product')
    return render(request, 'sales/refund_confirm.html', {
        'sale': sale,
        'lines': lines,
        'refunds': refunds,
        'left_total': sum((l['item'].unit_price * l['left'] for l in lines), Decimal('0')),
    })


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
import csv
import json
import calendar
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from django.utils import timezone
from django.db.models import Sum, F
from django.http import HttpResponse
from django.core.paginator import Paginator

from accounts.decorators import feature_required
from sales.models import Sale, SaleItem

from .ledger import refunds_given, refunds_given_by, sales_made, total_of

def _period_ledger(start, end):
    """Sales made, refunds given and the net, for a date range (see reports/ledger.py)."""
    made = sales_made(start, end).select_related('customer', 'cashier').order_by('created_at')
    refunds = refunds_given(start, end).select_related('customer', 'cashier', 'refunded_by').order_by('refund_time')
    gross = total_of(made)
    refunded = total_of(refunds)
    return {
        'made': made,
        'refunds': refunds,
        'gross_sales': gross,
        'refunds_total': refunded,
        'total': gross - refunded,
        'transaction_count': made.count(),
        'refund_count': refunds.count(),
    }


def _ledger_csv(filename, ledger, when_format):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(['#', 'Customer', 'Cashier', 'Status', 'Total', 'When'])
    for sale in ledger['made']:
        writer.writerow([
            sale.pk,
            str(sale.customer) if sale.customer else 'Walk-in',
            str(sale.cashier),
            sale.get_status_display(),
            sale.total,
            timezone.localtime(sale.created_at).strftime(when_format),
        ])
    writer.writerow([])
    writer.writerow(['REFUNDS GIVEN', '', 'Refunded by', 'Original sale', 'Amount', 'When'])
    for sale in ledger['refunds']:
        writer.writerow([
            sale.pk,
            str(sale.customer) if sale.customer else 'Walk-in',
            str(sale.refunded_by or sale.cashier),
            timezone.localtime(sale.created_at).strftime('%b %d, %Y'),
            -sale.total,
            timezone.localtime(sale.refund_time).strftime(when_format),
        ])
    writer.writerow([])
    writer.writerow(['', '', '', 'GROSS SALES', ledger['gross_sales'], ''])
    writer.writerow(['', '', '', 'LESS REFUNDS', -ledger['refunds_total'], ''])
    writer.writerow(['', '', '', 'NET', ledger['total'], ''])
    return response


def _ledger_context(ledger, request):
    page_obj = Paginator(ledger['made'], 11).get_page(request.GET.get('page', 1))
    return {
        'sales':             page_obj,
        'page_obj':          page_obj,
        'refunds':           ledger['refunds'],
        'gross_sales':       ledger['gross_sales'],
        'refunds_total':     ledger['refunds_total'],
        'total':             ledger['total'],
        'transaction_count': ledger['transaction_count'],
        'refund_count':      ledger['refund_count'],
    }


@feature_required('can_access_reports')
def daily_report(request):
    # --- Date Filter ---
    try:
        selected = datetime.strptime(request.GET.get('day', ''), '%Y-%m-%d').date()
    except ValueError:
        selected = timezone.localdate()

    ledger        = _period_ledger(selected, selected)
    selected_date = selected.strftime('%Y-%m-%d')

    if request.GET.get('export') == 'csv':
        return _ledger_csv(f'daily_report_{selected_date}.csv', ledger, '%H:%M')

    return render(request, 'reports/daily.html', {
        **_ledger_context(ledger, request),
        'date':          selected.strftime('%B %d, %Y'),
        'selected_date': selected_date,
    })


@feature_required('can_access_reports')
def monthly_report(request):
    now = timezone.localtime()

    # --- Filters ---
    try:
        selected_month = int(request.GET.get('month', now.month))
        selected_year  = int(request.GET.get('year',  now.year))
        date(selected_year, selected_month, 1)
    except ValueError:
        selected_month = now.month
        selected_year  = now.year

    first = date(selected_year, selected_month, 1)
    last  = date(selected_year, selected_month, calendar.monthrange(selected_year, selected_month)[1])
    ledger = _period_ledger(first, last)

    if request.GET.get('export') == 'csv':
        return _ledger_csv(f'monthly_report_{selected_year}_{selected_month:02d}.csv', ledger, '%b %d, %Y')

    months = [
        {'value': i, 'label': datetime(2000, i, 1).strftime('%B')}
        for i in range(1, 13)
    ]
    return render(request, 'reports/monthly.html', {
        **_ledger_context(ledger, request),
        'month_label':    first.strftime('%B %Y'),
        'selected_month': selected_month,
        'selected_year':  selected_year,
        'months':         months,
        'years':          list(range(now.year - 3, now.year + 1)),
    })


# ─── Analytics (unified Daily / Weekly / Monthly) ────────────────

@feature_required('can_access_reports')
def analytics(request):
    now = timezone.localtime()
    today = timezone.localdate()
    local_tz = timezone.get_current_timezone()
    mode = request.GET.get('mode', 'daily')
    modes = [('daily', 'Daily'), ('weekly', 'Weekly'), ('monthly', 'Monthly')]

    # ── Resolve selected period and previous period ───────────────
    if mode == 'weekly':
        week_param = request.GET.get('week', '')
        try:
            # HTML week input returns e.g. "2026-W20"; Monday = day 1
            curr_start = datetime.strptime(week_param + '-1', '%G-W%V-%u').date()
        except (ValueError, TypeError):
            curr_start = today - timedelta(days=today.weekday())
        curr_end = curr_start + timedelta(days=6)
        prev_start = curr_start - timedelta(weeks=1)
        prev_end = curr_end - timedelta(weeks=1)
        period_label = f"Week of {curr_start.strftime('%b %d')} – {curr_end.strftime('%b %d, %Y')}"
        prev_period_label = f"Week of {prev_start.strftime('%b %d')} – {prev_end.strftime('%b %d, %Y')}"
        selected_week = curr_start.strftime('%G-W%V')
        selected_date = ''
        selected_month = now.month
        selected_year = now.year

    elif mode == 'monthly':
        try:
            selected_month = int(request.GET.get('month', now.month))
            selected_year = int(request.GET.get('year', now.year))
        except ValueError:
            selected_month = now.month
            selected_year = now.year
        curr_start = date(selected_year, selected_month, 1)
        curr_end = date(selected_year, selected_month,
                        calendar.monthrange(selected_year, selected_month)[1])
        prev_month = selected_month - 1 or 12
        prev_year = selected_year if selected_month > 1 else selected_year - 1
        prev_start = date(prev_year, prev_month, 1)
        prev_end = date(prev_year, prev_month,
                        calendar.monthrange(prev_year, prev_month)[1])
        period_label = curr_start.strftime('%B %Y')
        prev_period_label = prev_start.strftime('%B %Y')
        selected_week = ''
        selected_date = ''

    else:  # daily
        mode = 'daily'
        day_param = request.GET.get('day', '')
        try:
            curr_start = datetime.strptime(day_param, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            curr_start = today
        curr_end = curr_start
        prev_start = curr_start - timedelta(days=1)
        prev_end = curr_start - timedelta(days=1)
        period_label = curr_start.strftime('%B %d, %Y')
        prev_period_label = prev_start.strftime('%B %d, %Y')
        selected_date = curr_start.strftime('%Y-%m-%d')
        selected_week = ''
        selected_month = now.month
        selected_year = now.year

    # ── Querysets ─────────────────────────────────────────────────
    curr_qs = Sale.objects.filter(
        status='completed',
        created_at__date__gte=curr_start,
        created_at__date__lte=curr_end,
    ).prefetch_related('items').order_by('-created_at')

    prev_qs = Sale.objects.filter(
        status='completed',
        created_at__date__gte=prev_start,
        created_at__date__lte=prev_end,
    ).prefetch_related('items')

    # ── Stats ─────────────────────────────────────────────────────
    curr_sales_list = list(curr_qs)
    prev_sales_list = list(prev_qs)

    curr_revenue = sum(s.total for s in curr_sales_list)
    prev_revenue = sum(s.total for s in prev_sales_list)
    curr_count = len(curr_sales_list)
    prev_count = len(prev_sales_list)
    curr_avg = (curr_revenue / curr_count) if curr_count else 0
    prev_avg = (prev_revenue / prev_count) if prev_count else 0

    def pct_delta(curr, prev):
        if not prev:
            return None
        return round(((float(curr) - float(prev)) / float(prev)) * 100, 1)

    revenue_delta = pct_delta(curr_revenue, prev_revenue)
    count_delta = pct_delta(curr_count, prev_count)
    avg_delta = pct_delta(curr_avg, prev_avg)

    # ── Chart data ────────────────────────────────────────────────
    from django.db.models.functions import TruncHour, TruncDate

    def sale_items_revenue(date_gte, date_lte):
        return (
            SaleItem.objects
            .filter(
                sale__status='completed',
                sale__created_at__date__gte=date_gte,
                sale__created_at__date__lte=date_lte,
            )
        )

    if mode == 'daily':
        # Hourly buckets 00:00 – 23:00
        chart_labels = [f'{h:02d}:00' for h in range(24)]

        def hourly(day):
            qs = (
                sale_items_revenue(day, day)
                .annotate(hr=TruncHour('sale__created_at', tzinfo=local_tz))
                .values('hr')
                .annotate(rev=Sum(F('quantity') * F('unit_price')))
            )
            m = {timezone.localtime(r['hr']).hour: float(r['rev']) for r in qs}
            return [m.get(h, 0) for h in range(24)]

        chart_curr = hourly(curr_start)
        chart_prev = hourly(prev_start)

    elif mode == 'weekly':
        # One bar per day of the week
        chart_labels = []
        d = curr_start
        while d <= curr_end:
            chart_labels.append(d.strftime('%a %d'))
            d += timedelta(days=1)

        def weekly_daily(start, end):
            qs = (
                sale_items_revenue(start, end)
                .annotate(day=TruncDate('sale__created_at', tzinfo=local_tz))
                .values('day')
                .annotate(rev=Sum(F('quantity') * F('unit_price')))
            )
            m = {r['day']: float(r['rev']) for r in qs}
            result, d = [], start
            while d <= end:
                result.append(m.get(d, 0))
                d += timedelta(days=1)
            return result

        chart_curr = weekly_daily(curr_start, curr_end)
        chart_prev = weekly_daily(prev_start, prev_end)

    else:  # monthly
        days_curr = calendar.monthrange(curr_start.year, curr_start.month)[1]
        days_prev = calendar.monthrange(prev_start.year, prev_start.month)[1]
        max_days = max(days_curr, days_prev)
        chart_labels = [str(d) for d in range(1, max_days + 1)]

        def monthly_daily(year, month, total_days):
            qs = (
                sale_items_revenue(date(year, month, 1),
                                   date(year, month, calendar.monthrange(year, month)[1]))
                .annotate(day=TruncDate('sale__created_at', tzinfo=local_tz))
                .values('day')
                .annotate(rev=Sum(F('quantity') * F('unit_price')))
            )
            m = {r['day'].day: float(r['rev']) for r in qs}
            data = [m.get(d, 0) for d in range(1, total_days + 1)]
            # Pad shorter month with None so Chart.js shows gap
            return data + [None] * (max_days - total_days)

        chart_curr = monthly_daily(curr_start.year, curr_start.month, days_curr)
        chart_prev = monthly_daily(prev_start.year, prev_start.month, days_prev)

    # ── CSV Export ────────────────────────────────────────────────
    if request.GET.get('export') == 'csv':
        filename = f"analytics_{mode}_{curr_start}.csv"
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        writer = csv.writer(response)
        writer.writerow(['#', 'Customer', 'Cashier', 'Total', 'Date/Time'])
        for sale in curr_sales_list:
            writer.writerow([
                sale.pk,
                str(sale.customer) if sale.customer else 'Walk-in',
                str(sale.cashier),
                sale.total,
                timezone.localtime(sale.created_at).strftime('%Y-%m-%d %H:%M'),
            ])
        writer.writerow([])
        writer.writerow(['', '', 'TOTAL', curr_revenue, ''])
        return response

    # ── Pagination ────────────────────────────────────────────────
    paginator = Paginator(curr_sales_list, 11)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    # ── Month/year dropdowns (for monthly filter UI) ──────────────
    months = [{'value': i, 'label': datetime(2000, i, 1).strftime('%B')} for i in range(1, 13)]
    years = list(range(now.year - 3, now.year + 1))

    return render(request, 'reports/analytics.html', {
        'mode': mode,
        'modes': modes,
        'period_label': period_label,
        'prev_period_label': prev_period_label,

        # Stats
        'curr_revenue': curr_revenue,
        'prev_revenue': prev_revenue,
        'revenue_delta': revenue_delta,
        'curr_count': curr_count,
        'prev_count': prev_count,
        'count_delta': count_delta,
        'curr_avg': round(curr_avg, 2),
        'prev_avg': round(prev_avg, 2),
        'avg_delta': avg_delta,

        # Chart
        'chart_labels': json.dumps(chart_labels),
        'chart_curr': json.dumps(chart_curr),
        'chart_prev': json.dumps(chart_prev),

        # Table + pagination
        'sales': page_obj,
        'page_obj': page_obj,

        # Filter state
        'selected_date': selected_date,
        'selected_week': selected_week,
        'selected_month': selected_month,
        'selected_year': selected_year,
        'months': months,
        'years': years,
    })


# ─── Cash Closing Report (Shift Report) ──────────────────────────
@feature_required('can_access_shift_report')
def shift_report(request):
    now = timezone.localtime()
    today = timezone.localdate()

    # --- Date Filter ---
    day_param = request.GET.get('day', '')
    try:
        selected_date = datetime.strptime(day_param, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        selected_date = today

    date_label = selected_date.strftime('%B %d, %Y')
    date_param = selected_date.strftime('%Y-%m-%d')

    # --- Cashier Filter ---
    cashier_id = request.GET.get('cashier', '')
    selected_cashier = None

    # --- Determine user role ---
    is_admin = request.user.is_superuser or request.user.is_staff

    # If cashier (not admin/staff), force filter to themselves
    if not is_admin:
        cashier_id = str(request.user.pk)  # Force to current user
        selected_cashier = request.user

    # --- Starting Cash (convert to Decimal) ---
    starting_cash = request.GET.get('starting_cash', '0')
    try:
        starting_cash = Decimal(str(starting_cash))
    except (ValueError, TypeError, InvalidOperation):
        starting_cash = Decimal('0.00')

    # --- Less Collection (convert to Decimal) ---
    less_collection = request.GET.get('less_collection', '0')
    try:
        less_collection = Decimal(str(less_collection))
    except (ValueError, TypeError, InvalidOperation):
        less_collection = Decimal('0.00')

    # --- Query: sales rung up this day (incl. ones refunded later) ---
    # See reports/ledger.py: sales count on the day made, refunds on the day given.
    sales_qs = sales_made(selected_date, selected_date)
    refunds_qs = refunds_given(selected_date, selected_date)

    # Apply cashier filter: their sales, and refunds they handed out
    if cashier_id:
        try:
            if not selected_cashier:
                selected_cashier = User.objects.get(pk=int(cashier_id))
            sales_qs = sales_qs.filter(cashier=selected_cashier)
            refunds_qs = refunds_given_by(refunds_qs, selected_cashier)
        except (ValueError, User.DoesNotExist):
            pass

    sales_qs = sales_qs.select_related('customer', 'cashier').order_by('created_at')

    # --- Calculations (all Decimal) ---
    # Only cash goes into the drawer; GCash/Maya/card/bank sales are settled
    # elsewhere and must not inflate the expected drawer amount.
    total_sales = Decimal('0.00')
    by_method = {}
    for s in sales_qs.prefetch_related('items'):
        sale_total = s.total if isinstance(s.total, Decimal) else Decimal(str(s.total))
        total_sales += sale_total
        by_method[s.payment_method] = by_method.get(s.payment_method, Decimal('0.00')) + sale_total

    cash_sales = by_method.pop('cash', Decimal('0.00'))
    non_cash_sales = total_sales - cash_sales
    method_labels = dict(Sale.PAYMENT_METHODS)
    non_cash_breakdown = [
        {'label': method_labels.get(method, method), 'amount': float(amount)}
        for method, amount in sorted(by_method.items(), key=lambda kv: -kv[1])
    ]

    # --- Refunds handed out this day ---
    total_refunds = total_of(refunds_qs)
    cash_refunds = total_of(refunds_qs.filter(payment_method='cash'))  # only these leave the drawer
    refund_count = refunds_qs.count()

    total_gross = starting_cash + cash_sales          # cash taken in, plus the float
    net_amount = total_gross - cash_refunds - less_collection
    transaction_count = sales_qs.count()
    avg_transaction = (total_sales / Decimal(str(transaction_count))) if transaction_count else Decimal('0.00')

    # --- Cashier list ---
    # Cashiers only see themselves in dropdown; admins/managers see all
    if is_admin:
        # Anyone who rang up a sale or handed out a refund (TenantManager scopes these)
        tenant_cashier_ids = set(
            Sale.objects.filter(status__in=('completed', 'refunded')).values_list('cashier_id', flat=True)
        ) | set(Sale.objects.exclude(refunded_by=None).values_list('refunded_by_id', flat=True))
        cashiers = User.objects.filter(pk__in=tenant_cashier_ids)
    else:
        cashiers = User.objects.filter(pk=request.user.pk)  # Only themselves

    return render(request, 'reports/shift_report.html', {
        'sales': sales_qs,
        'date_label': date_label,
        'selected_date': date_param,
        'selected_cashier': cashier_id,
        'cashiers': cashiers,
        'is_admin': is_admin,  # Pass to template for conditional UI

        'starting_cash': float(starting_cash),
        'total_sales': float(total_sales),
        'total_gross': float(total_gross),
        'less_collection': float(less_collection),
        'net_amount': float(net_amount),

        'transaction_count': transaction_count,
        'avg_transaction': float(avg_transaction),
        'total_refunds': float(total_refunds),
        'cash_refunds': float(cash_refunds),
        'refund_count': refund_count,
        'cash_sales': float(cash_sales),
        'non_cash_sales': float(non_cash_sales),
        'non_cash_breakdown': non_cash_breakdown,
    })
import calendar
import csv
import json
import logging
import math
import re
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from django.utils import timezone
from django.db import DatabaseError
from django.http import HttpResponse
from django.core.paginator import Paginator

from accounts.decorators import feature_required
from sales.models import Refund, Sale

from .ledger import (
    archived_refunds_given, archived_refunds_not_in_main, archived_sales_made,
    archived_total, refund_total_of, refunds_given, refunds_given_by, sales_made, total_of,
)

logger = logging.getLogger(__name__)

def _period_ledger(start, end):
    """Sales made, refunds given and the net, for a date range (see reports/ledger.py).
    Includes sales moved to the archive database; if it can't be reached the
    ledger covers the main database only and says so."""
    made = sales_made(start, end).select_related('customer', 'cashier').order_by('created_at')
    refunds = (refunds_given(start, end)
               .select_related('sale__customer', 'sale__cashier', 'refunded_by')
               .prefetch_related('items__sale_item__product').order_by('refunded_at', 'pk'))
    gross = total_of(made)
    refunded = refund_total_of(refunds)
    made_count, refund_count = made.count(), refunds.count()
    archive_unavailable = False

    try:
        arch_made = archived_sales_made(start, end)
        arch_refunds = archived_refunds_given(start, end)
        if arch_made.exists() or arch_refunds.exists():
            # A sale caught mid-move can be in both databases; count it once.
            arch_made = arch_made.exclude(pk__in=list(made.values_list('pk', flat=True)))
            arch_refunds = archived_refunds_not_in_main(arch_refunds, refunds).select_related('sale').prefetch_related('items')
            gross += archived_total(arch_made)
            refunded += archived_total(arch_refunds)
            made = sorted([*made, *arch_made], key=lambda s: s.created_at)
            refunds = sorted([*refunds, *arch_refunds], key=lambda r: r.refunded_at)
            made_count, refund_count = len(made), len(refunds)
    except DatabaseError:
        logger.exception('Archive database unavailable for report %s..%s', start, end)
        archive_unavailable = True

    return {
        'made': made,
        'refunds': refunds,
        'gross_sales': gross,
        'refunds_total': refunded,
        'total': gross - refunded,
        'transaction_count': made_count,
        'refund_count': refund_count,
        'archive_unavailable': archive_unavailable,
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
    for refund in ledger['refunds']:
        writer.writerow([
            refund.sale_id,
            str(refund.customer) if refund.customer else 'Walk-in',
            str(refund.given_by or ''),
            timezone.localtime(refund.sale_created_at).strftime('%b %d, %Y'),
            -refund.total,
            timezone.localtime(refund.refunded_at).strftime(when_format),
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
        'archive_unavailable': ledger['archive_unavailable'],
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


# ─── Analytics: real-time sales performance (see performance.py) ──
def _fmt(value, kind, signed=False):
    """A figure as text: 1,234 · ₱1,234.00 · 1.15. signed adds + / − (a real minus)."""
    if value is None:
        return '—'
    sign = ''
    if signed:
        sign = '+' if value > 0 else '−' if value < 0 else ''
        value = abs(value)
    if kind == 'int':
        return f'{sign}{value:,}'
    if kind == 'money':
        return f'{sign}₱{value:,.2f}'
    return f'{sign}{value:,.2f}'


def _fmt_tick(value, kind, thousands=False):
    """An axis label. thousands=True writes every tick in k, so one axis
    never mixes 7,500 with 10k."""
    if kind == 'ratio':
        return f'{value:g}'
    if thousands and value:
        text = f'{value / 1000:g}k'
    elif value == int(value):
        text = f'{value:,.0f}'
    else:
        text = f'{value:,.2f}'
    return f'₱{text}' if kind == 'money' else text


def _clock(dt):
    return f"{dt.hour % 12 or 12}:{dt:%M} {'AM' if dt.hour < 12 else 'PM'}"


def _performance(request):
    from . import performance as P

    period = request.GET.get('period', P.DEFAULT_PERIOD)
    period = period if period in P.PERIODS else P.DEFAULT_PERIOD
    metric = request.GET.get('metric', P.DEFAULT_METRIC)
    metric = metric if metric in P.METRICS else P.DEFAULT_METRIC
    metric_label, metric_kind = P.METRICS[metric]

    data = P.collect(period, timezone.now())
    series, step, n, now = data['series'], data['step'], data['n'], data['now']
    current, prior = series[0], series[1]

    def stop_of(s):
        """Positions with data: the current period stops at now; a shorter
        period (Feb against Jan) stops at its own end."""
        return data['last_bucket'] + 1 if s is current else data['lengths'][s.key]

    # ── What the changes are measured against ──
    cut = data['cut_at']
    if not data['is_partial']:
        compare_note = f'vs. {prior.label.lower()}'
    elif step == 'hour':
        compare_note = f'vs. {prior.label.lower()} through {_clock(cut)}'
    else:
        compare_note = f'vs. {prior.label.lower()} to the same point ({cut:%b} {cut.day}, {_clock(cut)})'

    # ── Figures ──
    tiles = []
    for key, (label, kind) in P.METRICS.items():
        curr, prev = data['so_far'].value(key), data['prior_so_far'].value(key)
        pct, diff = P.delta(curr, prev)
        tiles.append({
            'key': key, 'label': label, 'value': _fmt(curr, kind),
            'pct_abs': abs(pct) if pct is not None else None,
            'diff': _fmt(diff, kind, signed=True) if diff is not None else None,
            'direction': None if diff is None else 'up' if diff > 0 else 'down' if diff < 0 else 'flat',
        })

    # ── CSV export: every figure, every series, every position ──
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="sales_performance_{period}_{now:%Y-%m-%d}.csv"')
        writer = csv.writer(response)
        writer.writerow(['Sales performance', P.PERIODS[period], f'Generated {now:%Y-%m-%d %H:%M}'])
        writer.writerow(['Changes', compare_note])
        writer.writerow([])
        writer.writerow(['Figure', current.label, f'{prior.label} (same point)', 'Change', 'Change %'])
        for key, (label, kind) in P.METRICS.items():
            curr, prev = data['so_far'].value(key), data['prior_so_far'].value(key)
            pct, diff = P.delta(curr, prev)
            def raw(v, kind=kind):
                return '' if v is None else v if kind == 'int' else f'{v:.2f}'
            writer.writerow([label, raw(curr), raw(prev), raw(diff), '' if pct is None else pct])
        writer.writerow([])
        writer.writerow(['Position', 'Series', 'Units sold', 'Order items', 'Sales'])
        for s in series:
            for i, b in enumerate(s.buckets[:stop_of(s)]):
                writer.writerow([P.bucket_label(period, step, current, i, short=False), s.label,
                                 b.units, b.lines, f'{b.revenue:.2f}'])
        return response

    # ── Series values for the chosen figure; None where there's no data point ──
    values = {s.key: [b.value(metric) if i < stop_of(s) else None for i, b in enumerate(s.buckets)]
              for s in series}

    # ── Chart geometry: viewBox 1000 × 300, one polyline per unbroken run ──
    W, H = 1000, 300
    peak = max([float(v) for vals in values.values() for v in vals if v is not None] + [0])
    top, tick_step = P.nice_ceiling(peak)

    def x_of(i):
        return round(i / (n - 1) * W, 2) if n > 1 else W / 2

    def y_of(v):
        return round(H - float(v) / top * H, 2)

    chart_series = []
    for s in series:
        vals = values[s.key]
        segments, run = [], []
        for i, v in enumerate(vals):
            if v is None:
                if run:
                    segments.append(' '.join(run))
                run = []
            else:
                run.append(f'{x_of(i)},{y_of(v)}')
        if run:
            segments.append(' '.join(run))
        last = max((i for i, v in enumerate(vals) if v is not None), default=None)
        chart_series.append({
            'key': s.key, 'label': s.label, 'color': P.SERIES_COLORS[s.key], 'segments': segments,
            # The current line ends in a dot: "you are here".
            'end': ({'left': round(x_of(last) / W * 100, 2),
                     'bottom': round(float(vals[last]) / top * 100, 2)}
                    if s is current and last is not None else None),
        })

    ticks = [{'label': _fmt_tick(tick_step * k, metric_kind, thousands=top >= 10000),
              'pct': round(tick_step * k / top * 100, 2)}
             for k in range(int(round(top / tick_step)) + 1)]
    every = math.ceil(n / 8)
    # Up to 24 positions every label fits on a wide screen (minor ones drop
    # out on narrow ones); past that only every few are drawn at all.
    x_labels = [{'label': P.bucket_label(period, step, current, i),
                 'pct': round(x_of(i) / W * 100, 2),
                 'minor': i % every != 0,
                 'edge': 'start' if i == 0 else 'end' if i == n - 1 else ''}
                for i in range(n) if n <= 24 or i % every == 0]
    long_labels = [P.bucket_label(period, step, current, i, short=False) for i in range(n)]
    table_rows = [{'label': long_labels[i], 'cells': [_fmt(values[s.key][i], metric_kind) for s in series]}
                  for i in range(n)]
    hover = {
        'labels': long_labels,
        'series': [{'label': s.label, 'color': P.SERIES_COLORS[s.key],
                    'values': [None if v is None else _fmt(v, metric_kind) for v in values[s.key]]}
                   for s in series],
        'start': data['last_bucket'],
    }
    has_data = any(v for vals in values.values() for v in vals if v)

    print_name = re.sub(r'[\\/:*?"<>|]', '', f'Sales performance - {P.PERIODS[period]} - {now:%Y-%m-%d}')
    return render(request, 'reports/performance.html', {
        'tabs': ANALYTICS_TABS, 'tab': 'performance',
        'periods': list(P.PERIODS.items()), 'period': period, 'period_label': P.PERIODS[period],
        'metric': metric, 'metric_label': metric_label,
        'tiles': tiles, 'compare_note': compare_note, 'now': now,
        'chart_series': chart_series, 'ticks': ticks, 'x_labels': x_labels,
        'table_rows': table_rows, 'hover': hover, 'has_data': has_data,
        'chart_title': f'{metric_label} by {step}',
        'archive_unavailable': not data['archive_ok'],
        # PDF export (partials/dashboard_print.html)
        'print_section': 'Analytics', 'print_title': 'Sales performance',
        'print_period': f'{P.PERIODS[period]} · {metric_label} · {compare_note}',
        'print_landscape': True, 'print_filename_json': json.dumps(print_name),
    })


# ─── Analytics › Trends (see trends.py) ──────────────────────────
def _line_chart(values, kind, n):
    """Geometry for one small line chart: points share the bar charts' slots,
    (i + ½) / n across, so every chart on the tab lines up."""
    from . import performance as P
    peak = max([float(v) for v in values if v is not None] + [0])
    top, step = P.nice_ceiling(peak)
    def x(i):
        return (i + 0.5) / n
    runs, run = [], []
    for i, v in enumerate(values):
        if v is None:
            if run:
                runs.append(' '.join(run))
            run = []
        else:
            run.append(f'{round(x(i) * 1000, 2)},{round(200 - float(v) / top * 200, 2)}')
    if run:
        runs.append(' '.join(run))
    return {
        'segments': runs,
        'dots': [{'left': round(x(i) * 100, 2), 'bottom': round(float(v) / top * 100, 2)}
                 for i, v in enumerate(values) if v is not None],
        'ticks': [{'label': _fmt_tick(step * k, kind, thousands=top >= 10000),
                   'pct': round(step * k / top * 100, 2)}
                  for k in range(int(round(top / step)) + 1)],
        'has_data': any(values),
    }


def _trends(request):
    from . import performance as P
    from . import trends as T

    def pick(name, default, allowed):
        value = request.GET.get(name, default)
        return value if value in allowed else default

    cadence = pick('cadence', T.DEFAULT_CADENCE, T.CADENCES)
    m1 = pick('metric', 'revenue', P.METRICS)
    m2 = pick('compare', 'units', P.METRICS)
    yoy = pick('yoy', 'units', P.METRICS)
    now = timezone.localtime()
    data = T.collect(cadence, now)
    periods, n = data['periods'], len(data['periods'])

    def values(totals, metric):
        return [t.value(metric) if t is not None else None for t in totals]

    def ly_label(p):
        if not p.ly_start:
            return 'No matching week last year'
        if cadence == 'weekly':
            return f"Wk {p.ly_start.isocalendar()[1]} · {T._span(p.ly_start, p.ly_end - timedelta(days=1))}"
        if cadence == 'monthly':
            return f'{p.ly_start:%B %Y}'
        return f"Q{(p.ly_start.month - 1) // 3 + 1} {p.ly_start.year}"

    # ── CSV: every figure, every period, with last year beside it ──
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="sales_trends_{cadence}_{now:%Y-%m-%d}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Sales trends', T.CADENCES[cadence], f'Generated {now:%Y-%m-%d %H:%M}'])
        writer.writerow([])
        header = ['Period', 'Same period last year']
        for label, _ in P.METRICS.values():
            header += [label, f'{label} last year', f'{label} change %']
        writer.writerow(header)
        for p, cur, ly in zip(periods, data['current'], data['last_year']):
            row = [p.long_label, ly_label(p)]
            for key, (_, kind) in P.METRICS.items():
                a, b = cur.value(key), (ly.value(key) if ly else None)
                pct, _ = P.delta(a, b)
                def raw(v, kind=kind):
                    return '' if v is None else v if kind == 'int' else f'{v:.2f}'
                row += [raw(a), raw(b), '' if pct is None else pct]
            writer.writerow(row)
        return response

    # ── Two figures over time: two small charts on one time axis ──
    pair = []
    for key, color in ((m1, '#0A5FA8'), (m2, '#D2601A')):
        label, kind = P.METRICS[key]
        vals = values(data['current'], key)
        pair.append({'key': key, 'label': label, 'color': color, 'kind': kind,
                     'chart': _line_chart(vals, kind, n),
                     'cells': [_fmt(v, kind) for v in vals]})

    # ── Year over year: this period against the same one a year back ──
    yoy_label, yoy_kind = P.METRICS[yoy]
    cur_vals, ly_vals = values(data['current'], yoy), values(data['last_year'], yoy)
    peak = max([float(v) for v in cur_vals + ly_vals if v is not None] + [0])
    top, step = P.nice_ceiling(peak)
    groups = []
    for p, a, b in zip(periods, cur_vals, ly_vals):
        pct, diff = P.delta(a, b)
        groups.append({
            'label': p.label, 'long': p.long_label, 'ly_long': ly_label(p),
            'cur_pct': round(float(a or 0) / top * 100, 2), 'cur_txt': _fmt(a, yoy_kind),
            'ly_pct': None if b is None else round(float(b) / top * 100, 2), 'ly_txt': _fmt(b, yoy_kind),
            'pct_abs': abs(pct) if pct is not None else None,
            'direction': None if diff is None else 'up' if diff > 0 else 'down' if diff < 0 else 'flat',
        })
    yoy_ticks = [{'label': _fmt_tick(step * k, yoy_kind, thousands=top >= 10000),
                  'pct': round(step * k / top * 100, 2)} for k in range(int(round(top / step)) + 1)]

    hover = {'labels': [p.long_label for p in periods],
             'series': [{'label': s['label'], 'color': s['color'], 'values': s['cells']} for s in pair]}
    print_name = re.sub(r'[\\/:*?"<>|]', '', f'Sales trends - {T.CADENCES[cadence]} - {now:%Y-%m-%d}')
    return render(request, 'reports/trends.html', {
        'tabs': ANALYTICS_TABS, 'tab': 'trends',
        'cadences': list(T.CADENCES.items()), 'cadence': cadence,
        'metrics': [(k, label) for k, (label, _) in P.METRICS.items()],
        'm1': m1, 'm2': m2, 'yoy': yoy, 'yoy_label': yoy_label,
        'periods': periods, 'pair': pair, 'groups': groups, 'yoy_ticks': yoy_ticks,
        'pair_rows': [{'label': p.long_label, 'cells': [s['cells'][i] for s in pair]}
                      for i, p in enumerate(periods)],
        'yoy_has_data': any(cur_vals) or any(v for v in ly_vals if v),
        'hover': hover, 'now': now, 'n': n, 'span_label': f'Last {n} complete {T.PLURAL[cadence]}',
        'archive_unavailable': not data['archive_ok'],
        'print_section': 'Analytics', 'print_title': 'Sales trends',
        'print_period': f'Last {n} {T.PLURAL[cadence]} · {pair[0]["label"]} & {pair[1]["label"]} '
                        f'· {yoy_label} year over year',
        'print_landscape': True, 'print_filename_json': json.dumps(print_name),
    })


# (tab, label, Bootstrap icon) — Records-style tabs along the top of the page
ANALYTICS_TABS = [('performance', 'Performance', 'bi-activity'), ('trends', 'Trends', 'bi-bar-chart-line')]


@feature_required('can_access_reports')
def analytics(request):
    if request.GET.get('tab') == 'trends':
        return _trends(request)
    return _performance(request)


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
    method_counts = {}
    for s in sales_qs.prefetch_related('items'):
        sale_total = s.total if isinstance(s.total, Decimal) else Decimal(str(s.total))
        total_sales += sale_total
        by_method[s.payment_method] = by_method.get(s.payment_method, Decimal('0.00')) + sale_total
        method_counts[s.payment_method] = method_counts.get(s.payment_method, 0) + 1
    method_labels = dict(Sale.PAYMENT_METHODS)
    method_rows = [
        {
            'label': method_labels.get(method, method),
            'amount': float(amount),
            'count': method_counts[method],
            'pct': round(float(amount) / float(total_sales) * 100, 1) if total_sales else 0,
            'is_cash': method == 'cash',
        }
        for method, amount in sorted(by_method.items(), key=lambda kv: -kv[1])
    ]

    cash_sales = by_method.pop('cash', Decimal('0.00'))
    non_cash_sales = total_sales - cash_sales
    non_cash_breakdown = [
        {'label': method_labels.get(method, method), 'amount': float(amount)}
        for method, amount in sorted(by_method.items(), key=lambda kv: -kv[1])
    ]

    # --- Refunds handed out this day ---
    total_refunds = refund_total_of(refunds_qs)
    cash_refunds = refund_total_of(refunds_qs.filter(sale__payment_method='cash'))  # only these leave the drawer
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
        ) | set(Refund.objects.exclude(refunded_by=None).values_list('refunded_by_id', flat=True))
        cashiers = User.objects.filter(pk__in=tenant_cashier_ids)
    else:
        cashiers = User.objects.filter(pk=request.user.pk)  # Only themselves

    def day_query(day):
        q = f"day={day:%Y-%m-%d}"
        if is_admin and cashier_id:
            q += f"&cashier={cashier_id}"
        return q

    return render(request, 'reports/shift_report.html', {
        'date_label': date_label,
        'prev_day_query': day_query(selected_date - timedelta(days=1)),
        'next_day_query': day_query(selected_date + timedelta(days=1)),
        'is_today': selected_date >= today,
        'cashier_name': selected_cashier.username if selected_cashier else '',
        'method_rows': method_rows,
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
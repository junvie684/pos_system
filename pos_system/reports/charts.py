"""
Dashboard Chart tab: one measure over time (by month, week or day) and
breakdowns of the same period (payment method, category, top products, hour of
day, day of week, cashier).

Same money rules as the reports (see ledger.py): a sale counts when it was
made, a refund when the money went back. Archived sales are included.
"""
import logging
import math
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import DatabaseError
from django.db.models import Count, F, Sum
from django.db.models.functions import ExtractHour, ExtractIsoWeekDay, TruncDate

from sales.models import SaleItem

from .ledger import ZERO, archived_sales_made, sales_made
from .pnl import PAYMENT_LABELS, _collect, _day, _not_in_main
from .tiles import _add_months, date_label, group_rows, product_rows

logger = logging.getLogger(__name__)

RANGES = {
    '12m': 'Last 12 months, by month',
    '3m':  'Last 3 months, by week',
    '30d': 'Last 30 days, by day',
}
DEFAULT_RANGE = '12m'

METRICS = {
    'sales':  ('Sales', 'money'),
    'net':    ('Net sales', 'money'),
    'txns':   ('Orders', 'int'),
    'units':  ('Units sold', 'int'),
    'refunds': ('Refunds', 'int'),
    'avg':    ('Average sale', 'money'),
}
DEFAULT_METRIC = 'sales'
WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


# ── Time buckets ────────────────────────────────────────────────
def range_dates(key, today, custom=None):
    """(start, end, step) for a range choice; step is 'month', 'week' or 'day'."""
    if key == 'custom' and custom:
        start, end = custom
        days = (end - start).days + 1
        step = 'day' if days <= 62 else 'week' if days <= 26 * 7 else 'month'
        return start, end, step
    if key == '3m':
        week = today - timedelta(days=today.weekday())
        return week - timedelta(weeks=12), today, 'week'
    if key == '30d':
        return today - timedelta(days=29), today, 'day'
    return _add_months(today.replace(day=1), -11), today, 'month'


def _bucket_start(d, step):
    if step == 'month':
        return d.replace(day=1)
    if step == 'week':
        return d - timedelta(days=d.weekday())
    return d


def _next(d, step):
    if step == 'month':
        return _add_months(d, 1)
    return d + timedelta(days=7 if step == 'week' else 1)


def _bucket_labels(b, step, start, end, first):
    """(axis label, axis sub-label, full label for tooltips and the summary)."""
    b_end = min(_next(b, step) - timedelta(days=1), end)
    b_start = max(b, start)
    full = date_label(b_start, b_end)
    if step == 'month':
        return f'{b:%b}', (str(b.year) if first or b.month == 1 else ''), full
    if step == 'week':
        return f'{b_start:%b} {b_start.day}', '', full
    return str(b.day), (f'{b:%b}' if first or b.day == 1 else ''), full


def nice_ticks(top, count=4):
    """Round axis steps (1, 2, 2.5 or 5 x 10^n) covering 0..top."""
    if top <= 0:
        return [0, 1]
    raw = top / count
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    n = math.ceil(top / step)
    return [step * i for i in range(n + 1)]


def tick_text(value, kind):
    """Short axis label: no decimals unless the step needs them."""
    text = f'{value:,.2f}'.rstrip('0').rstrip('.') if value % 1 else f'{int(value):,}'
    return f'₱{text}' if kind == 'money' else text


def _metric_value(fig, metric):
    if metric == 'net':
        return fig['sales'] - fig['refund_cost']
    if metric == 'avg':
        return fig['sales'] / fig['txns'] if fig['txns'] else None
    return fig[metric]


def _empty():
    return {'sales': ZERO, 'units': 0, 'txns': 0, 'refunds': 0, 'refund_cost': ZERO,
            'by_method': defaultdict(lambda: ZERO)}


def _add(into, fig):
    for k in ('sales', 'units', 'txns', 'refunds', 'refund_cost'):
        into[k] += fig[k]
    for code, amount in fig['by_method'].items():
        into['by_method'][code] += amount


def summary(fig):
    """The figures listed beside the chart."""
    net = fig['sales'] - fig['refund_cost']
    return [
        {'label': 'Sales', 'value': fig['sales'], 'kind': 'money', 'strong': True},
        {'label': 'Orders', 'value': fig['txns'], 'kind': 'int'},
        {'label': 'Units sold', 'value': fig['units'], 'kind': 'int'},
        {'label': 'Refunds', 'value': fig['refunds'], 'kind': 'int'},
        {'label': 'Refund cost', 'value': -fig['refund_cost'], 'kind': 'money'},
        {'label': 'Net sales', 'value': net, 'kind': 'money', 'strong': True},
        {'label': 'Average sale', 'value': fig['sales'] / fig['txns'] if fig['txns'] else None, 'kind': 'money'},
        {'label': 'Units per order', 'value': fig['units'] / fig['txns'] if fig['txns'] else None, 'kind': 'dec'},
        {'label': 'Refund rate', 'value': fig['refunds'] * 100 / fig['txns'] if fig['txns'] else None, 'kind': 'pct'},
    ]


def time_series(start, end, step, metric, today):
    """Columns for the main chart, the whole-period figures and the latest bucket's."""
    daily, archive_unavailable = _collect(end, start, trunc=TruncDate, key=_day)
    buckets = []
    b = _bucket_start(start, step)
    while b <= end:
        fig = _empty()
        d = max(b, start)
        stop = min(_next(b, step) - timedelta(days=1), end)
        while d <= stop:
            if d in daily:
                _add(fig, daily[d])
            d += timedelta(days=1)
        label, sub, full = _bucket_labels(b, step, start, end, not buckets)
        buckets.append({'label': label, 'sub': sub, 'full': full, 'fig': fig,
                        'value': _metric_value(fig, metric),
                        'is_current': b <= today <= stop})
        b = _next(b, step)

    values = [float(x['value'] or 0) for x in buckets]
    ticks = nice_ticks(max(values, default=0))
    top = ticks[-1] or 1
    for x, v in zip(buckets, values):
        x['pct'] = round(v / top * 100, 2)

    total = _empty()
    for x in buckets:
        _add(total, x['fig'])
    payments = sorted(
        ((PAYMENT_LABELS.get(code, code), amount) for code, amount in total['by_method'].items() if amount),
        key=lambda kv: -kv[1],
    )
    return {
        'buckets': buckets,
        'ticks': [{'value': t, 'pct': round(t / top * 100, 2)} for t in reversed(ticks)],
        'total': total,
        'payments': payments,
        'archive_unavailable': archive_unavailable,
    }


# ── Breakdowns of the whole period ──────────────────────────────
def bars(pairs, limit=None):
    """[(label, value)] -> rows with a width % against the largest, biggest first."""
    pairs = sorted(((k, v) for k, v in pairs if v), key=lambda kv: -kv[1])
    total = sum((v for _, v in pairs), ZERO)
    if limit:
        pairs = pairs[:limit]
    top = float(pairs[0][1]) if pairs else 1
    return [{'label': k, 'value': v, 'pct': round(float(v) / top * 100, 1),
             'share': round(float(v / total * 100), 1) if total else None} for k, v in pairs], total


def by_clock(start, end):
    """Sales made per hour of day and per weekday: ({hour: amount}, {1..7: amount})."""
    made = sales_made(start, end)
    hours, days = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    lines = SaleItem.objects.filter(sale__in=made.values('pk')).order_by()
    amount = Sum(F('quantity') * F('unit_price'))
    for r in lines.annotate(h=ExtractHour('sale__created_at')).values('h').annotate(a=amount):
        hours[r['h']] += r['a'] or ZERO
    for r in lines.annotate(w=ExtractIsoWeekDay('sale__created_at')).values('w').annotate(a=amount):
        days[r['w']] += r['a'] or ZERO
    try:
        arch = _not_in_main(archived_sales_made(start, end), made).order_by()
        for r in arch.annotate(h=ExtractHour('created_at')).values('h').annotate(a=Sum('total')):
            hours[r['h']] += r['a'] or ZERO
        for r in arch.annotate(w=ExtractIsoWeekDay('created_at')).values('w').annotate(a=Sum('total')):
            days[r['w']] += r['a'] or ZERO
    except DatabaseError:
        logger.exception('Archive database unavailable for dashboard charts')
    return hours, days


def by_cashier(start, end):
    """[(name, sales amount, order count)] for sales made in the range."""
    made = sales_made(start, end)
    rows = defaultdict(lambda: {'amount': ZERO, 'orders': 0, 'name': ''})
    for r in (SaleItem.objects.filter(sale__in=made.values('pk')).order_by()
              .values('sale__cashier_id').annotate(a=Sum(F('quantity') * F('unit_price')))):
        rows[r['sale__cashier_id']]['amount'] += r['a'] or ZERO
    for r in made.order_by().values('cashier_id').annotate(n=Count('pk')):
        rows[r['cashier_id']]['orders'] += r['n']
    try:
        arch = _not_in_main(archived_sales_made(start, end), made).order_by()
        for r in arch.values('cashier_id', 'cashier_name').annotate(a=Sum('total'), n=Count('pk')):
            row = rows[r['cashier_id']]
            row['amount'] += r['a'] or ZERO
            row['orders'] += r['n']
            row['name'] = row['name'] or r['cashier_name']
    except DatabaseError:
        logger.exception('Archive database unavailable for dashboard charts')
    users = {u.pk: (u.get_full_name() or u.username) for u in User.objects.filter(pk__in=[k for k in rows if k])}
    return [(users.get(k) or v['name'] or 'Unknown', v['amount'], v['orders']) for k, v in rows.items()]



def breakdowns(start, end):
    products, products_unavailable = product_rows(start, end)
    hours, days = by_clock(start, end)

    hour_rows = []
    open_hours = [h for h in range(24) if hours.get(h)]
    if open_hours:
        lo, hi = min(open_hours), max(open_hours)
        top = float(max(hours.values())) or 1
        for h in range(lo, hi + 1):
            v = hours.get(h, ZERO)
            label = f'{(h % 12) or 12}{"a" if h < 12 else "p"}'
            hour_rows.append({'label': label, 'full': f'{(h % 12) or 12}:00 {"AM" if h < 12 else "PM"}',
                              'value': v, 'pct': round(float(v) / top * 100, 1)})
    day_top = float(max(days.values(), default=0)) or 1
    day_rows = [{'label': WEEKDAYS[i - 1], 'full': WEEKDAYS[i - 1], 'value': days.get(i, ZERO),
                 'pct': round(float(days.get(i, ZERO)) / day_top * 100, 1)} for i in range(1, 8)]

    cashiers = by_cashier(start, end)
    cashier_rows, _ = bars([(name, amount) for name, amount, _ in cashiers])
    orders = {name: n for name, _, n in cashiers}
    for r in cashier_rows:
        r['orders'] = orders.get(r['label'], 0)

    categories, _ = bars([(g['name'], g['sales']) for g in group_rows(products)])
    top_products, _ = bars([(p['name'], p['sales']) for p in products], limit=10)
    return {
        'categories': categories,
        'top_products': top_products,
        'hours': hour_rows,
        'weekdays': day_rows,
        'cashiers': cashier_rows,
        'archive_unavailable': products_unavailable,
    }

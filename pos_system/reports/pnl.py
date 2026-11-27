"""
Profit & loss table for the dashboard's P&L tab: one column per month, newest
first, plus a total.

Same money rules as the daily and monthly reports (see ledger.py): a sale counts
in the month it was made, a refund in the month the money went back. Sales
moved to the archive database are included; if it can't be reached the table
covers the main database only and says so.

The POS records no product costs, fees or expenses, so the table stops at net
sales: there is no cost of goods or profit line to show.
"""
import logging
from collections import defaultdict
from datetime import date, datetime

from django.db import DatabaseError
from django.db.models import Count, F, Max, Sum
from django.db.models.functions import TruncMonth

from sales.models import RefundItem, Sale, SaleItem

from .ledger import (
    ZERO, archived_refunds_given, archived_refunds_not_in_main, archived_sales_made, refunds_given, sales_made,
)

logger = logging.getLogger(__name__)

PERIODS = (3, 6, 12, 24)
DEFAULT_PERIOD = 12
PAYMENT_LABELS = dict(Sale.PAYMENT_METHODS)


def month_starts(today, months):
    """First day of each of the last `months` months, newest first."""
    y, m = today.year, today.month
    out = []
    for _ in range(months):
        out.append(date(y, m, 1))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out


def _month(value):
    if isinstance(value, datetime):
        value = value.date()
    return value.replace(day=1)


def _not_in_main(arch_qs, main_qs):
    """Archived sales minus any still in the main database (a run that stopped
    mid-move). Only main rows up to the newest archived ID can overlap."""
    newest = arch_qs.aggregate(m=Max('pk'))['m']
    if newest is None:
        return arch_qs.none()
    overlap = list(main_qs.filter(pk__lte=newest).values_list('pk', flat=True))
    return arch_qs.exclude(pk__in=overlap) if overlap else arch_qs


def _day(value):
    return value.date() if isinstance(value, datetime) else value


def _collect(today, first, trunc=TruncMonth, key=_month):
    """Raw figures per bucket (per month by default; pass TruncDate/_day for
    per day): {bucket: {...}} plus whether the archive was missing."""
    data = defaultdict(lambda: {
        'sales': ZERO, 'units': 0, 'txns': 0, 'refunds': 0, 'refund_cost': ZERO,
        'by_method': defaultdict(lambda: ZERO),
    })

    made = sales_made(first, today)
    for row in (SaleItem.objects.filter(sale__in=made.values('pk'))
                .annotate(m=trunc('sale__created_at'))
                .values('m', 'sale__payment_method').order_by()
                .annotate(amount=Sum(F('quantity') * F('unit_price')), units=Sum('quantity'))):
        d = data[key(row['m'])]
        d['sales'] += row['amount'] or ZERO
        d['units'] += row['units'] or 0
        d['by_method'][row['sale__payment_method']] += row['amount'] or ZERO
    for row in made.annotate(m=trunc('created_at')).values('m').order_by().annotate(n=Count('pk')):
        data[key(row['m'])]['txns'] += row['n']

    refunds = refunds_given(first, today)
    for row in (RefundItem.objects.filter(refund__in=refunds.values('pk'))
                .annotate(m=trunc('refund__refunded_at'))
                .values('m').order_by()
                .annotate(amount=Sum(F('quantity') * F('unit_price')))):
        data[key(row['m'])]['refund_cost'] += row['amount'] or ZERO
    for row in refunds.annotate(m=trunc('refunded_at')).values('m').order_by().annotate(n=Count('pk')):
        data[key(row['m'])]['refunds'] += row['n']

    archive_unavailable = False
    try:
        from archive.models import ArchivedSaleItem
        arch_made = _not_in_main(archived_sales_made(first, today), made)
        for row in (ArchivedSaleItem.objects.filter(sale__in=arch_made.values('pk'))
                    .annotate(m=trunc('sale__created_at'))
                    .values('m', 'sale__payment_method').order_by()
                    .annotate(amount=Sum(F('quantity') * F('unit_price')), units=Sum('quantity'))):
            d = data[key(row['m'])]
            d['sales'] += row['amount'] or ZERO
            d['units'] += row['units'] or 0
            d['by_method'][row['sale__payment_method']] += row['amount'] or ZERO
        for row in arch_made.annotate(m=trunc('created_at')).values('m').order_by().annotate(n=Count('pk')):
            data[key(row['m'])]['txns'] += row['n']

        arch_refunds = archived_refunds_not_in_main(archived_refunds_given(first, today), refunds)
        for row in (arch_refunds.annotate(m=trunc('refunded_at')).values('m').order_by()
                    .annotate(n=Count('pk'), amount=Sum('total'))):
            d = data[key(row['m'])]
            d['refunds'] += row['n']
            d['refund_cost'] += row['amount'] or ZERO
    except DatabaseError:
        logger.exception('Archive database unavailable for P&L')
        archive_unavailable = True

    return data, archive_unavailable


def _ratio(a, b):
    return (a / b) if b else None


def build_pnl(today, months=DEFAULT_PERIOD):
    """Columns and rows for the P&L table. Each row value is a number, or None
    where it can't be worked out (an average with no sales)."""
    starts = month_starts(today, months)
    data, archive_unavailable = _collect(today, starts[-1])

    columns = []
    for m in starts:
        if m.year == today.year and m.month == today.month:
            label = f"{m:%B} 1–{today.day}"
        elif m.year == today.year:
            label = f"{m:%B}"
        else:
            label = f"{m:%B %Y}"
        columns.append({'label': label, 'current': m == starts[0]})

    cells = [data.get(m) or data.default_factory() for m in starts]
    total = {
        k: sum((c[k] for c in cells), ZERO if k in ('sales', 'refund_cost') else 0)
        for k in ('sales', 'units', 'txns', 'refunds', 'refund_cost')
    }

    def row(key, label, kind, fn, children=None, strong=False):
        return {
            'key': key, 'label': label, 'kind': kind, 'strong': strong,
            'values': [fn(c) for c in cells], 'total': fn(total),
            'children': children or [],
        }

    methods = sorted(
        {code for c in cells for code, amount in c['by_method'].items() if amount},
        key=lambda code: -sum(c['by_method'].get(code, ZERO) for c in cells),
    )
    method_rows = []
    for code in methods:
        values = [c['by_method'].get(code, ZERO) for c in cells]
        method_rows.append({
            'key': f'sales-{code}', 'label': PAYMENT_LABELS.get(code, code), 'kind': 'money',
            'values': values, 'total': sum(values, ZERO), 'children': [], 'strong': False,
        })

    rows = [
        row('sales', 'Sales', 'money', lambda c: c['sales'], children=method_rows),
        row('units', 'Units sold', 'int', lambda c: c['units']),
        row('txns', 'Transactions', 'int', lambda c: c['txns']),
        row('refunds', 'Refunds', 'int', lambda c: c['refunds']),
        row('refund_cost', 'Refund cost', 'money', lambda c: -c['refund_cost']),
        row('net', 'Net sales', 'money', lambda c: c['sales'] - c['refund_cost'], strong=True),
        row('avg', 'Average sale', 'money', lambda c: _ratio(c['sales'], c['txns'])),
        row('units_per', 'Units per sale', 'dec', lambda c: _ratio(c['units'], c['txns'])),
        row('refund_rate', 'Refund rate', 'pct', lambda c: _ratio(c['refunds'] * 100, c['txns'])),
    ]
    return {'columns': columns, 'rows': rows, 'archive_unavailable': archive_unavailable}


def fmt(value, kind):
    """Display text for one P&L cell."""
    if value is None:
        return '—'
    if kind == 'money':
        sign = '−' if value < 0 else ''
        return f"{sign}₱{abs(value):,.2f}"
    if kind == 'pct':
        return f"{value:.2f}%"
    if kind == 'dec':
        return f"{value:,.2f}"
    return f"{value:,}"

"""
Dashboard tiles: a row of period summaries (Today, Yesterday, Month to date, ...)
and, for the selected tile, a per-product table and the sale lines behind it.

Same money rules as the reports (see ledger.py): a sale counts on the day it
was made, a refund on the day the money went back. Archived sales are included.
"""
import calendar
import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import DatabaseError
from django.db.models import F, Sum
from django.db.models.functions import TruncDate

from products.models import Product
from sales.models import RefundItem, SaleItem

from .ledger import (
    ZERO, archived_refunds_given, archived_refunds_not_in_main, archived_sales_made, refunds_given, sales_made,
)
from .pnl import PAYMENT_LABELS, _collect, _day, _not_in_main

logger = logging.getLogger(__name__)

PRESETS = {
    'default':  'Today / Yesterday / Month to date / This month (forecast) / Last month',
    'mtd':      'Today / Yesterday / Month to date / Last month',
    'rolling':  'Today / Yesterday / 7 days / 14 days / 30 days',
    'weeks':    'This week / Last week / 2 weeks ago / 3 weeks ago',
    'months':   'Month to date / Last month / 2 months ago / 3 months ago',
    'days':     'Today / Yesterday / 2 days ago / 3 days ago',
    'weekday':  'Today / Yesterday / 7 days ago / 8 days ago',
    'quarters': 'This quarter / Last quarter / 2 quarters ago / 3 quarters ago',
}
DEFAULT_PRESET = 'default'
ORDER_ITEMS_LIMIT = 300


# ── Calendar helpers ────────────────────────────────────────────
def _add_months(d, n):
    """First day of the month `n` months from d's month."""
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, m + 1, 1)


def _month_end(first):
    return first.replace(day=calendar.monthrange(first.year, first.month)[1])


def _quarter_start(d):
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


class Period:
    """One tile: a date range, the range it is compared against, and whether
    its figures are projected to the end of the month."""

    def __init__(self, title, start, end, compare=None, forecast_end=None):
        self.title, self.start, self.end = title, start, end
        self.compare = compare
        self.forecast_end = forecast_end

    @property
    def days(self):
        return (self.end - self.start).days + 1


def _day_period(title, d):
    return Period(title, d, d, (d - timedelta(days=1), d - timedelta(days=1)))


def _span_period(title, start, end):
    """A range compared against the same number of days just before it."""
    n = (end - start).days + 1
    return Period(title, start, end, (start - timedelta(days=n), start - timedelta(days=1)))


def _month_period(title, first):
    prev = _add_months(first, -1)
    return Period(title, first, _month_end(first), (prev, _month_end(prev)))


def _to_date_period(title, first, today, step_months):
    """Month or quarter to date, compared with the same days of the period before."""
    prev = _add_months(first, -step_months)
    offset = (today - first).days
    prev_end = min(prev + timedelta(days=offset), first - timedelta(days=1))
    return Period(title, first, today, (prev, prev_end))


def _quarter_period(title, first):
    prev = _add_months(first, -3)
    return Period(title, first, _add_months(first, 3) - timedelta(days=1),
                  (prev, first - timedelta(days=1)))


def build_periods(preset, today, custom=None):
    month = today.replace(day=1)
    week = today - timedelta(days=today.weekday())
    quarter = _quarter_start(today)
    today_p = _day_period('Today', today)
    yesterday_p = _day_period('Yesterday', today - timedelta(days=1))
    mtd = _to_date_period('Month to date', month, today, 1)
    last_month = _month_period('Last month', _add_months(month, -1))

    if preset == 'custom' and custom:
        start, end = custom
        return [_span_period('Custom range', start, end)]
    if preset == 'mtd':
        return [today_p, yesterday_p, mtd, last_month]
    if preset == 'rolling':
        return [today_p, yesterday_p] + [
            _span_period(f'{n} days', today - timedelta(days=n - 1), today) for n in (7, 14, 30)
        ]
    if preset == 'weeks':
        this_week = Period('This week', week, today,
                           (week - timedelta(days=7), today - timedelta(days=7)))
        return [this_week] + [
            _span_period(label, week - timedelta(days=7 * n), week - timedelta(days=7 * n - 6))
            for n, label in ((1, 'Last week'), (2, '2 weeks ago'), (3, '3 weeks ago'))
        ]
    if preset == 'months':
        return [mtd, last_month] + [
            _month_period(f'{n} months ago', _add_months(month, -n)) for n in (2, 3)
        ]
    if preset == 'days':
        return [today_p, yesterday_p] + [
            _day_period(f'{n} days ago', today - timedelta(days=n)) for n in (2, 3)
        ]
    if preset == 'weekday':
        return [today_p, yesterday_p] + [
            _day_period(f'{n} days ago', today - timedelta(days=n)) for n in (7, 8)
        ]
    if preset == 'quarters':
        this_q = _to_date_period('This quarter', quarter, today, 3)
        return [this_q, _quarter_period('Last quarter', _add_months(quarter, -3))] + [
            _quarter_period(f'{n} quarters ago', _add_months(quarter, -3 * n)) for n in (2, 3)
        ]
    # default
    forecast = Period('This month (forecast)', month, today,
                      (last_month.start, last_month.end), forecast_end=_month_end(month))
    return [today_p, yesterday_p, mtd, forecast, last_month]


def date_label(start, end):
    if start == end:
        return f'{start:%B} {start.day}, {start.year}'
    if (start.year, start.month) == (end.year, end.month):
        return f'{start:%B} {start.day}–{end.day}, {end.year}'
    if start.year == end.year:
        return f'{start:%b} {start.day} – {end:%b} {end.day}, {end.year}'
    return f'{start:%b} {start.day}, {start.year} – {end:%b} {end.day}, {end.year}'


# ── Tile figures ────────────────────────────────────────────────
def _sum_days(daily, start, end):
    out = {'sales': ZERO, 'units': 0, 'txns': 0, 'refunds': 0, 'refund_cost': ZERO,
           'by_method': defaultdict(lambda: ZERO)}
    d = start
    while d <= end:
        row = daily.get(d)
        if row:
            for k in ('sales', 'units', 'txns', 'refunds', 'refund_cost'):
                out[k] += row[k]
            for code, amount in row['by_method'].items():
                out['by_method'][code] += amount
        d += timedelta(days=1)
    return out


def _finish(fig):
    fig['net'] = fig['sales'] - fig['refund_cost']
    fig['avg'] = fig['sales'] / fig['txns'] if fig['txns'] else None
    fig['units_per'] = fig['units'] / fig['txns'] if fig['txns'] else None
    fig['methods'] = [
        {'label': PAYMENT_LABELS.get(code, code), 'amount': amount}
        for code, amount in sorted(fig.pop('by_method').items(), key=lambda kv: -kv[1]) if amount
    ]
    return fig


def _pct_change(curr, prev):
    if not prev:
        return None
    return round(float((curr - prev) / prev * 100), 1)


def build_tiles(periods, today):
    """Figures for each period, plus whether the archive database was missing."""
    earliest = min(min(p.start, p.compare[0] if p.compare else p.start) for p in periods)
    daily, archive_unavailable = _collect(today, earliest, trunc=TruncDate, key=_day)

    tiles = []
    for p in periods:
        fig = _sum_days(daily, p.start, min(p.end, today))
        if p.forecast_end:
            factor = Decimal((p.forecast_end - p.start).days + 1) / Decimal(p.days)
            for k in ('sales', 'refund_cost'):
                fig[k] = (fig[k] * factor).quantize(ZERO)
            for k in ('units', 'txns', 'refunds'):
                fig[k] = round(fig[k] * factor)
            for code in fig['by_method']:
                fig['by_method'][code] = (fig['by_method'][code] * factor).quantize(ZERO)
        fig = _finish(fig)
        delta = None
        if p.compare:
            prev = _sum_days(daily, *p.compare)
            delta = _pct_change(fig['sales'], prev['sales'])
        tiles.append({
            'title': p.title,
            'dates': date_label(p.start, p.forecast_end or p.end),
            'forecast': bool(p.forecast_end),
            'delta': delta,
            'delta_abs': abs(delta) if delta is not None else None,
            **fig,
        })
    return tiles, archive_unavailable


# ── Product table and order items for one period ────────────────
def _empty_product():
    return {'units': 0, 'sales': ZERO, 'refund_units': 0, 'refund_cost': ZERO}


def product_rows(start, end):
    """Per-product figures for a date range: sales made in it, refunds given in it."""
    made, refunds = sales_made(start, end), refunds_given(start, end)
    rows, names = defaultdict(_empty_product), {}

    def key(pid, name):
        k = pid if pid is not None else f'name:{name}'
        names.setdefault(k, name)
        return k

    for r in (SaleItem.objects.filter(sale__in=made.values('pk'))
              .values('product_id', 'product__name').order_by()
              .annotate(units=Sum('quantity'), sales=Sum(F('quantity') * F('unit_price')))):
        row = rows[key(r['product_id'], r['product__name'])]
        row['units'] += r['units'] or 0
        row['sales'] += r['sales'] or ZERO
    for r in (RefundItem.objects.filter(refund__in=refunds.values('pk'))
              .values('sale_item__product_id', 'sale_item__product__name').order_by()
              .annotate(units=Sum('quantity'), amount=Sum(F('quantity') * F('unit_price')))):
        row = rows[key(r['sale_item__product_id'], r['sale_item__product__name'])]
        row['refund_units'] += r['units'] or 0
        row['refund_cost'] += r['amount'] or ZERO

    archive_unavailable = False
    try:
        from archive.models import ArchivedRefundItem, ArchivedSaleItem
        arch_made = _not_in_main(archived_sales_made(start, end), made)
        arch_refunds = archived_refunds_not_in_main(archived_refunds_given(start, end), refunds)
        for model, link, qs, units_key, money_key in (
            (ArchivedSaleItem, 'sale__in', arch_made, 'units', 'sales'),
            (ArchivedRefundItem, 'refund__in', arch_refunds, 'refund_units', 'refund_cost'),
        ):
            for r in (model.objects.filter(**{link: qs.values('pk')})
                      .values('product_id', 'product_name').order_by()
                      .annotate(units=Sum('quantity'), amount=Sum(F('quantity') * F('unit_price')))):
                row = rows[key(r['product_id'], r['product_name'])]
                row[units_key] += r['units'] or 0
                row[money_key] += r['amount'] or ZERO
    except DatabaseError:
        logger.exception('Archive database unavailable for dashboard products')
        archive_unavailable = True

    products = {
        p.pk: p for p in Product.objects.filter(pk__in=[k for k in rows if isinstance(k, int)])
        .select_related('category')
    }
    total_sales = sum((r['sales'] for r in rows.values()), ZERO)
    out = []
    for k, r in rows.items():
        product = products.get(k)
        out.append({
            **r,
            'name': product.name if product else names[k],
            'category': (product.category.name if product and product.category else 'Uncategorized'),
            'stock': product.stock if product else None,
            'net': r['sales'] - r['refund_cost'],
            'share': float(r['sales'] / total_sales * 100) if total_sales else None,
            'asp': r['sales'] / r['units'] if r['units'] else None,
        })
    out.sort(key=lambda r: (-r['units'], -r['sales'], r['name'].lower()))
    return out, archive_unavailable


def group_rows(rows):
    """Products grouped by category, biggest category (by units) first, with subtotals."""
    groups = defaultdict(list)
    for r in rows:
        groups[r['category']].append(r)
    total_sales = sum((r['sales'] for r in rows), ZERO)
    out = []
    for name, items in groups.items():
        g = {k: sum((r[k] for r in items), ZERO if k in ('sales', 'refund_cost', 'net') else 0)
             for k in ('units', 'sales', 'refund_units', 'refund_cost', 'net')}
        g.update(
            name=name, items=items, count=len(items),
            share=float(g['sales'] / total_sales * 100) if total_sales else None,
            asp=g['sales'] / g['units'] if g['units'] else None,
        )
        out.append(g)
    out.sort(key=lambda g: (-g['units'], -g['sales'], g['name'].lower()))
    return out


def order_items(start, end, limit=ORDER_ITEMS_LIMIT):
    """Sale lines made in the range, newest first (main database, then archive).
    Returns (lines, total line count)."""
    made = sales_made(start, end)
    main = (SaleItem.objects.filter(sale__in=made.values('pk'))
            .select_related('sale', 'sale__cashier', 'product')
            .order_by('-sale__created_at', '-pk'))
    total = main.count()
    lines = list(main[:limit])
    try:
        from archive.models import ArchivedSaleItem
        arch = ArchivedSaleItem.objects.filter(
            sale__in=_not_in_main(archived_sales_made(start, end), made).values('pk')
        ).select_related('sale').order_by('-sale__created_at', '-pk')
        total += arch.count()
        if len(lines) < limit:
            lines += list(arch[:limit - len(lines)])
    except DatabaseError:
        logger.exception('Archive database unavailable for dashboard order items')
    return lines, total

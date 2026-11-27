"""
Sales figures for products: units sold, revenue, transactions, total cost
(COGS) and gross profit. One set of rules for the Products tab (every
product) and a product's history page (one product).

Cost rules
* A sale line counts at the cost saved on it when the sale was made.
* Lines sold before costs were saved have none: they count at the product's
  current cost, and the note says how many units that covers.
* Lines with no cost then and no cost now are left out of both cost and
  gross profit (otherwise their whole revenue would look like profit).

Only completed sales count, as on the history page.
"""
import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db import DatabaseError
from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from sales.models import SaleItem

from .models import Product

logger = logging.getLogger(__name__)
ZERO = Decimal('0.00')

PERIODS = {
    '7d': 'Last 7 days',
    '30d': 'Last 30 days',
    '90d': 'Last 90 days',
    'year': 'This year',
    'all': 'All time',
}
DEFAULT_PERIOD = '30d'


def period_dates(key, today=None):
    """(first day or None for all time, last day) for a period choice."""
    today = today or timezone.localdate()
    if key == 'all':
        return None, today
    if key == 'year':
        return today.replace(month=1, day=1), today
    return today - timedelta(days=int(key[:-1]) - 1), today


def _plural(n):
    return f'{n} unit{"s" if n != 1 else ""}'


@dataclass
class Figures:
    units: int = 0
    revenue: Decimal = ZERO
    transactions: int = 0
    total_cost: Decimal = None
    cost_note: str = ''
    gross_profit: Decimal = None
    margin: Decimal = None
    profit_note: str = ''
    archive_ok: bool = True

    @property
    def units_per_sale(self):
        return self.units / self.transactions if self.transactions else None

    @property
    def gross_profit_abs(self):
        return None if self.gross_profit is None else abs(self.gross_profit)


class _Tally:
    """Adds sale lines up, in the database where it can."""
    def __init__(self):
        self.units = 0
        self.revenue = ZERO
        self.transactions = 0
        self.saved_cost = ZERO          # lines with a saved cost
        self.saved_revenue = ZERO
        self.saved_units = 0
        self.unsaved = {}               # product_id → [units, revenue] for lines without one

    def add(self, qs):
        row = qs.aggregate(
            units=Sum('quantity'),
            revenue=Sum(F('quantity') * F('unit_price')),
            transactions=Count('sale', distinct=True),
            saved_cost=Sum(F('quantity') * F('unit_cost'), filter=Q(unit_cost__isnull=False)),
            saved_revenue=Sum(F('quantity') * F('unit_price'), filter=Q(unit_cost__isnull=False)),
            saved_units=Sum('quantity', filter=Q(unit_cost__isnull=False)),
        )
        self.units += row['units'] or 0
        self.revenue += row['revenue'] or ZERO
        self.transactions += row['transactions'] or 0
        self.saved_cost += row['saved_cost'] or ZERO
        self.saved_revenue += row['saved_revenue'] or ZERO
        self.saved_units += row['saved_units'] or 0
        for r in (qs.filter(unit_cost__isnull=True).values('product_id')
                  .annotate(u=Sum('quantity'), rev=Sum(F('quantity') * F('unit_price')))):
            slot = self.unsaved.setdefault(r['product_id'], [0, ZERO])
            slot[0] += r['u'] or 0
            slot[1] += r['rev'] or ZERO


def _scope(start, end, product_ids=None, include_archive=False):
    """(main lines, archived lines or None, archive reachable) for completed
    sales between two local dates; start None means from the beginning."""
    main = SaleItem.objects.filter(sale__status='completed', sale__created_at__date__lte=end)
    if start:
        main = main.filter(sale__created_at__date__gte=start)
    if product_ids is not None:
        main = main.filter(product_id__in=product_ids)
    if not include_archive:
        return main, None, True
    try:
        from archive.models import ArchivedSaleItem
        arch = ArchivedSaleItem.objects.filter(sale__status='completed', sale__created_at__date__lte=end)
        if start:
            arch = arch.filter(sale__created_at__date__gte=start)
        if product_ids is not None:
            arch = arch.filter(product_id__in=product_ids)
        # A run that stopped mid-move can leave a sale in both databases.
        newest = arch.order_by('-sale_id').values_list('sale_id', flat=True).first()
        if newest is None:
            return main, None, True
        overlap = list(main.filter(sale_id__lte=newest).values_list('sale_id', flat=True).distinct())
        return main, (arch.exclude(sale_id__in=overlap) if overlap else arch), True
    except DatabaseError:
        logger.exception('Archive database unavailable for product figures')
        return main, None, False


def _finish(tally, today_cost, has_cost_now):
    """Figures from a tally, by the cost rules at the top of this file.
    today_cost maps product id → its current cost (None: no cost)."""
    out = Figures()
    fallback_cost, fallback_revenue, fallback_units, uncosted_units = ZERO, ZERO, 0, 0
    for pid, (units, revenue) in tally.unsaved.items():
        cost = today_cost.get(pid)
        if cost is None:
            uncosted_units += units
        else:
            fallback_cost += units * cost
            fallback_revenue += revenue
            fallback_units += units

    out.units, out.revenue, out.transactions = tally.units, tally.revenue, tally.transactions
    costed_units = tally.saved_units + fallback_units
    if not tally.units:
        out.total_cost = ZERO if has_cost_now else None
        out.cost_note = '' if out.total_cost is None else 'No sales in this period'
    elif not costed_units:
        out.total_cost = None        # nothing sold had a cost: nothing to count with
    else:
        out.total_cost = tally.saved_cost + fallback_cost
        notes = []
        if fallback_units:
            notes.append(f"{_plural(fallback_units)} at today's cost (sold before costs were saved)")
        if uncosted_units:
            notes.append(f'{_plural(uncosted_units)} without a cost left out')
        out.cost_note = '; '.join(notes) or 'at the cost when each sale was made'

    if out.total_cost is not None:
        costed_revenue = tally.saved_revenue + fallback_revenue
        out.gross_profit = costed_revenue - out.total_cost
        out.margin = round(out.gross_profit / costed_revenue * 100, 1) if costed_revenue else None
        if uncosted_units:
            out.profit_note = f'excludes {_plural(uncosted_units)} without a cost'
    return out


def figures(start, end, product=None, include_archive=False):
    """Figures for completed sales between two local dates (start None: from
    the beginning), for one product or all of them."""
    main, arch, archive_ok = _scope(start, end, None if product is None else [product.pk], include_archive)
    tally = _Tally()
    tally.add(main)
    if arch is not None:
        tally.add(arch)

    if product is not None:
        today_cost, has_cost_now = {product.pk: product.cost}, product.cost is not None
    else:
        today_cost = dict(Product.objects.filter(pk__in=[k for k in tally.unsaved if k])
                          .values_list('pk', 'cost'))
        has_cost_now = Product.objects.filter(is_active=True, cost__isnull=False).exists()
    out = _finish(tally, today_cost, has_cost_now)
    out.archive_ok = archive_ok
    return out


def figures_by_product(start, end, products, include_archive=False):
    """{product id: Figures} for a list of products, in one grouped query per
    database rather than one per product."""
    ids = [p.pk for p in products]
    main, arch, archive_ok = _scope(start, end, ids, include_archive)
    tallies = {pid: _Tally() for pid in ids}
    for qs in (main, arch):
        if qs is None:
            continue
        for r in qs.values('product_id').annotate(
            units=Sum('quantity'),
            revenue=Sum(F('quantity') * F('unit_price')),
            transactions=Count('sale', distinct=True),
            saved_cost=Sum(F('quantity') * F('unit_cost'), filter=Q(unit_cost__isnull=False)),
            saved_revenue=Sum(F('quantity') * F('unit_price'), filter=Q(unit_cost__isnull=False)),
            saved_units=Sum('quantity', filter=Q(unit_cost__isnull=False)),
            unsaved_units=Sum('quantity', filter=Q(unit_cost__isnull=True)),
            unsaved_revenue=Sum(F('quantity') * F('unit_price'), filter=Q(unit_cost__isnull=True)),
        ).order_by():
            t = tallies.get(r['product_id'])
            if t is None:
                continue
            t.units += r['units'] or 0
            t.revenue += r['revenue'] or ZERO
            t.transactions += r['transactions'] or 0
            t.saved_cost += r['saved_cost'] or ZERO
            t.saved_revenue += r['saved_revenue'] or ZERO
            t.saved_units += r['saved_units'] or 0
            if r['unsaved_units']:
                slot = t.unsaved.setdefault(r['product_id'], [0, ZERO])
                slot[0] += r['unsaved_units']
                slot[1] += r['unsaved_revenue'] or ZERO
    out = {}
    for p in products:
        out[p.pk] = _finish(tallies[p.pk], {p.pk: p.cost}, p.cost is not None)
        out[p.pk].archive_ok = archive_ok
    return out

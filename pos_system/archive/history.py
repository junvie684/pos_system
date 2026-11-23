"""
Sales history across both databases.

Archiving always moves a store's oldest paid sales, so every archived sale is
older than every paid sale still in the main database. Newest-first history is
therefore: main-database sales, then archived sales. TimelineList joins the two
querysets into one sequence the Paginator can count and slice, fetching only
the rows on the requested page.
"""
import logging
import re

from django.db import DatabaseError
from django.db.models import Max, Q, Sum

from .models import ArchivedSale

logger = logging.getLogger(__name__)


class TimelineList:
    def __init__(self, main_qs, archived_qs=None):
        self.main = main_qs
        self.archived = archived_qs
        self._main_count = main_qs.count()
        self._archived_count = archived_qs.count() if archived_qs is not None else 0

    def count(self):
        return self._main_count + self._archived_count

    def __len__(self):
        return self.count()

    def __getitem__(self, index):
        if not isinstance(index, slice):
            return list(self[index:index + 1])[0]
        start, stop = index.start or 0, index.stop if index.stop is not None else self.count()
        rows = list(self.main[start:min(stop, self._main_count)]) if start < self._main_count else []
        if self.archived is not None and stop > self._main_count:
            a_start, a_stop = max(start - self._main_count, 0), stop - self._main_count
            rows += list(self.archived[a_start:a_stop])
        return rows


def archived_history(main_qs, query='', date_from=None, date_to=None):
    """This store's archived sales matching the history filters, newest first,
    or None if the archive database can't be reached."""
    try:
        qs = ArchivedSale.objects.filter(status__in=('completed', 'refunded'))
        if query:
            match = (Q(customer_name__icontains=query) | Q(cashier_name__icontains=query)
                     | Q(status__icontains=query))
            digits = re.sub(r'^\s*or[\s#-]*', '', query, flags=re.I).strip()
            if digits.isdigit():
                match |= Q(or_number=int(digits)) | Q(pk=int(digits))
            qs = qs.filter(match)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        # A sale caught mid-move can be in both databases; show the live one.
        newest = qs.aggregate(m=Max('pk'))['m']
        if newest is not None:
            in_main = list(main_qs.filter(pk__lte=newest).values_list('pk', flat=True))
            if in_main:
                qs = qs.exclude(pk__in=in_main)
        qs = qs.order_by('-created_at', '-pk').prefetch_related('items')
        qs.exists()          # touch the database now, so failures land here
        return qs
    except DatabaseError:
        logger.exception('Archive database unavailable for sales history')
        return None


def archived_summary(qs):
    """(completed total, completed count, refunded count) for archived sales."""
    if qs is None:
        return 0, 0, 0
    completed = qs.filter(status='completed')
    total = completed.aggregate(t=Sum('total'))['t'] or 0
    return total, completed.count(), qs.filter(status='refunded').count()


def archived_dashboard_totals(main_paid_qs):
    """All-time archived figures for the dashboard, or None if the archive
    database can't be reached:
        {'products': {name: {'revenue', 'units'}},
         'cashiers': {username: {'sales_count', 'revenue'}},
         'completed': n, 'refunded': n}
    Sales caught mid-move (still in `main_paid_qs`) are left out so they
    aren't counted twice."""
    from django.db.models import Count, F

    from .models import ArchivedSaleItem
    try:
        sales = ArchivedSale.objects.filter(status__in=('completed', 'refunded'))
        newest = sales.aggregate(m=Max('pk'))['m']
        if newest is None:
            return {'products': {}, 'cashiers': {}, 'completed': 0, 'refunded': 0}
        in_main = list(main_paid_qs.filter(pk__lte=newest).values_list('pk', flat=True))
        if in_main:
            sales = sales.exclude(pk__in=in_main)

        completed = sales.filter(status='completed')
        products = {
            row['product_name']: {'revenue': row['revenue'] or 0, 'units': row['units'] or 0}
            for row in ArchivedSaleItem.objects
            .filter(sale__in=completed.values('pk'))
            .values('product_name')
            .annotate(revenue=Sum(F('quantity') * F('unit_price')), units=Sum('quantity'))
        }
        cashiers = {
            row['cashier_name']: {'sales_count': row['n'], 'revenue': row['revenue'] or 0}
            for row in completed.exclude(cashier_name='')
            .values('cashier_name').annotate(n=Count('pk'), revenue=Sum('total'))
        }
        return {
            'products': products,
            'cashiers': cashiers,
            'completed': completed.count(),
            'refunded': sales.filter(status='refunded').count(),
        }
    except DatabaseError:
        logger.exception('Archive database unavailable for dashboard')
        return None

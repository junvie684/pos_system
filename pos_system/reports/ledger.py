"""
Money-report rules (daily, monthly, shift):

* A sale counts on the day it was MADE, even if it is refunded later.
* A refund counts, as a deduction, on the day the money went BACK.
  Refunds are per item (sales.Refund / RefundItem): a sale can be refunded in
  parts on different days, and each part counts on its own day.

So closing a day never changes afterwards. Refunds recorded before refund
dates existed were dated to their sale's own day when they were converted,
which nets that day to zero (exactly what the old reports showed).

Analytics (dashboard, top products, product history) keep showing figures
net of refunds by current status; that answers "what is selling", not
"what cash moved when".
"""
from decimal import Decimal

from django.db.models import F, Q, Sum, Value
from django.db.models.functions import Coalesce

from sales.models import Refund, RefundItem, Sale, SaleItem

SOLD_STATUSES = ('completed', 'refunded')
ZERO = Decimal('0.00')


def sales_made(start, end):
    """Sales rung up between two local dates (inclusive), refunded or not."""
    return Sale.objects.filter(
        status__in=SOLD_STATUSES,
        created_at__date__gte=start,
        created_at__date__lte=end,
    )


def refunds_given(start, end):
    """Refunds (sales.Refund) whose money went back between two local dates (inclusive)."""
    return Refund.objects.filter(refunded_at__date__gte=start, refunded_at__date__lte=end)


def refunds_given_by(qs, user):
    """Refunds handed out by `user` (legacy refunds: the original cashier)."""
    return qs.filter(Q(refunded_by=user) | Q(refunded_by__isnull=True, sale__cashier=user))


def refund_total_of(refunds_qs):
    """Money handed back by a queryset of refunds, as Decimal."""
    return RefundItem.objects.filter(refund__in=refunds_qs.values('pk')).aggregate(
        t=Coalesce(Sum(F('quantity') * F('unit_price')), Value(ZERO))
    )['t']


def total_of(sales_qs):
    """Sum of line totals for a queryset of sales, as Decimal."""
    return SaleItem.objects.filter(sale__in=sales_qs.values('pk')).aggregate(
        t=Coalesce(Sum(F('quantity') * F('unit_price')), Value(ZERO))
    )['t']


# ── Archived sales (pos_archive database) ───────────────────────
# Same rules as above, for sales moved out of the main database. They are
# read separately (the two databases can't be joined) and merged in Python.

def archived_sales_made(start, end):
    from archive.models import ArchivedSale
    return ArchivedSale.objects.filter(
        status__in=SOLD_STATUSES, created_at__date__gte=start, created_at__date__lte=end,
    )


def archived_refunds_given(start, end):
    """Archived refunds (archive.ArchivedRefund) given between two local dates."""
    from archive.models import ArchivedRefund
    return ArchivedRefund.objects.filter(refunded_at__date__gte=start, refunded_at__date__lte=end)


def archived_refunds_not_in_main(arch_refunds, main_refunds):
    """Archived refunds minus those whose sale is still in the main database
    (a run that stopped mid-move). Matched by sale: refund IDs differ."""
    from django.db.models import Max
    newest = arch_refunds.aggregate(m=Max('sale_id'))['m']
    if newest is None:
        return arch_refunds.none()
    overlap = list(main_refunds.filter(sale_id__lte=newest).values_list('sale_id', flat=True))
    return arch_refunds.exclude(sale_id__in=overlap) if overlap else arch_refunds


def archived_total(qs):
    return qs.aggregate(t=Coalesce(Sum('total'), Value(ZERO)))['t']

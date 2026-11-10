"""
Money-report rules (daily, monthly, shift):

* A sale counts on the day it was MADE, even if it is refunded later.
* A refund counts, as a deduction, on the day the money went BACK.

So closing a day never changes afterwards. Refunds recorded before
`refunded_at` existed have no refund date; they are dated to their sale's
own day, which nets that day to zero (exactly what the old reports showed).

Analytics (dashboard, top products, product history) keep showing figures
net of refunds by current status; that answers "what is selling", not
"what cash moved when".
"""
from decimal import Decimal

from django.db.models import DateTimeField, F, Q, Sum, Value
from django.db.models.functions import Coalesce

from sales.models import Sale, SaleItem

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
    """Refunded sales whose money went back between two local dates (inclusive)."""
    return (
        Sale.objects.filter(status='refunded')
        .annotate(refund_time=Coalesce('refunded_at', 'created_at', output_field=DateTimeField()))
        .filter(refund_time__date__gte=start, refund_time__date__lte=end)
    )


def refunds_given_by(qs, user):
    """Refunds handed out by `user` (legacy refunds: the original cashier)."""
    return qs.filter(Q(refunded_by=user) | Q(refunded_by__isnull=True, cashier=user))


def total_of(sales_qs):
    """Sum of line totals for a queryset of sales, as Decimal."""
    return SaleItem.objects.filter(sale__in=sales_qs.values('pk')).aggregate(
        t=Coalesce(Sum(F('quantity') * F('unit_price')), Value(ZERO))
    )['t']

"""
Moving paid sales from the main database to the pos_archive database.

For each batch, the sales are locked in the main database (so a refund can't
change one mid-move), copied into the archive and committed there, and only
then deleted from the main database. The two databases can't share one
transaction, so the order matters: if anything fails after the archive commit,
the sales are still in the main database and the next run copies them again,
replacing the earlier copy. A sale is never in neither place.
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.db import DatabaseError, transaction
from django.db.models import F, Prefetch, Sum
from django.utils import timezone

from sales.models import Refund, RefundItem, Sale, SaleItem
from tenants.models import Tenant

from .models import ArchivedRefund, ArchivedRefundItem, ArchivedSale, ArchivedSaleItem
from .routers import ARCHIVE_DB

logger = logging.getLogger(__name__)

PAID_STATUSES = ('completed', 'refunded')
BATCH_SIZE = 500


def cutoff_for(store, now=None):
    """Sales made before this moment are past the store's retention period."""
    return (now or timezone.now()) - timedelta(days=store.retention_days)


def eligible_sales(store, now=None):
    return Sale.all_objects.filter(
        tenant_id=store.id, status__in=PAID_STATUSES, created_at__lt=cutoff_for(store, now),
    )


def _copy(sales):
    """Archive rows (sales, items) for fully loaded Sale objects."""
    archived, lines = [], []
    for sale in sales:
        items = list(sale.items.all())
        archived.append(ArchivedSale(
            id=sale.pk,
            tenant_id=sale.tenant_id,
            or_number=sale.or_number,
            status=sale.status,
            payment_method=sale.payment_method,
            reference_number=sale.reference_number,
            cash_tendered=sale.cash_tendered,
            change_given=sale.change_given,
            total=sum((i.quantity * i.unit_price for i in items), start=Decimal('0.00')),
            created_at=sale.created_at,
            refunded_at=sale.refunded_at,
            customer_id=sale.customer_id,
            customer_name=sale.customer.name if sale.customer else '',
            cashier_id=sale.cashier_id,
            cashier_name=sale.cashier.get_username() if sale.cashier else '',
            refunded_by_name=sale.refunded_by.get_username() if sale.refunded_by else '',
        ))
        for item in items:
            lines.append(ArchivedSaleItem(
                tenant_id=sale.tenant_id,
                sale_id=sale.pk,
                product_id=item.product_id,
                product_name=item.product.name,
                product_barcode=item.product.barcode or '',
                quantity=item.quantity,
                unit_price=item.unit_price,
            ))
    return archived, lines


def _copy_refunds(sales):
    """[(ArchivedRefund, [ArchivedRefundItem])] for fully loaded Sale objects."""
    out = []
    for sale in sales:
        for refund in sale.refunds.all():
            items = [
                ArchivedRefundItem(
                    tenant_id=sale.tenant_id,
                    product_id=ri.sale_item.product_id,
                    product_name=ri.sale_item.product.name,
                    quantity=ri.quantity,
                    unit_price=ri.unit_price,
                    restocked=ri.restocked,
                )
                for ri in refund.items.all()
            ]
            out.append((ArchivedRefund(
                tenant_id=sale.tenant_id,
                sale_id=sale.pk,
                refunded_at=refund.refunded_at,
                refunded_by_name=refund.refunded_by.get_username() if refund.refunded_by else '',
                total=sum((i.quantity * i.unit_price for i in items), start=Decimal('0.00')),
            ), items))
    return out


def archive_store(store, now=None, batch_size=BATCH_SIZE):
    """Move every paid sale past the store's retention period. Returns how many moved."""
    moved = 0
    while True:
        with transaction.atomic(using='default'):
            ids = list(
                eligible_sales(store, now).order_by('pk')
                .select_for_update().values_list('pk', flat=True)[:batch_size]
            )
            if not ids:
                break
            # Lines via the unscoped manager: the store-scoped default manager
            # returns nothing when no store is in context (e.g. the nightly job).
            sales = list(
                Sale.all_objects.filter(pk__in=ids)
                .select_related('customer', 'cashier', 'refunded_by')
                .prefetch_related(
                    Prefetch('items', queryset=SaleItem.all_objects.select_related('product')),
                    Prefetch('refunds', queryset=Refund.all_objects.select_related('refunded_by').prefetch_related(
                        Prefetch('items', queryset=RefundItem.all_objects.select_related('sale_item__product')))),
                )
            )
            archived, lines = _copy(sales)
            refunds = _copy_refunds(sales)
            in_main = SaleItem.all_objects.filter(sale_id__in=ids).count()
            if len(lines) != in_main:
                # Never delete lines that weren't copied; roll the batch back.
                raise RuntimeError(f'Archive copy has {len(lines)} lines, main database has {in_main}.')

            with transaction.atomic(using=ARCHIVE_DB):
                # Replace any copy left by an earlier run that stopped halfway.
                ArchivedRefundItem.all_objects.filter(refund__sale_id__in=ids).delete()
                ArchivedRefund.all_objects.filter(sale_id__in=ids).delete()
                ArchivedSaleItem.all_objects.filter(sale_id__in=ids).delete()
                ArchivedSale.all_objects.filter(pk__in=ids).delete()
                ArchivedSale.all_objects.bulk_create(archived)
                ArchivedSaleItem.all_objects.bulk_create(lines)
                for refund, items in refunds:
                    refund.save()
                    for item in items:
                        item.refund = refund
                    ArchivedRefundItem.all_objects.bulk_create(items)

            RefundItem.all_objects.filter(refund__sale_id__in=ids).delete()
            Refund.all_objects.filter(sale_id__in=ids).delete()
            SaleItem.all_objects.filter(sale_id__in=ids).delete()
            Sale.all_objects.filter(pk__in=ids).delete()
        moved += len(ids)

    Tenant.objects.filter(pk=store.pk).update(
        last_archived_at=timezone.now(), last_archive_count=moved,
    )
    logger.info('Archived %s sale(s) for store %s', moved, store.slug)
    return moved


def retention_status(store, now=None):
    """Figures for the store's Data retention card. Archive figures are None
    when the archive database can't be reached."""
    status = {
        'cutoff': cutoff_for(store, now),
        'waiting': eligible_sales(store, now).count(),
        'archived': None,
        'archived_total': None,
        'oldest_archived': None,
        'archive_error': False,
    }
    try:
        qs = ArchivedSale.all_objects.filter(tenant_id=store.id)
        agg = qs.aggregate(total=Sum(F('total')))
        status['archived'] = qs.count()
        status['archived_total'] = agg['total']
        status['oldest_archived'] = qs.order_by('created_at').values_list('created_at', flat=True).first()
    except DatabaseError:
        logger.exception('Archive database unavailable')
        status['archive_error'] = True
    return status

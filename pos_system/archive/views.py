"""Archived sales are listed in Sales History; this reprints one's receipt."""
import logging
from decimal import Decimal

from django.contrib import messages
from django.db import DatabaseError
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import pos_login_required
from tenants.models import Tenant

from .models import ArchivedSale

logger = logging.getLogger(__name__)


@pos_login_required
def archived_receipt(request, sale_id):
    """Receipt of an archived sale of the signed-in store (read-only copy)."""
    try:
        sale = get_object_or_404(ArchivedSale.objects.prefetch_related('items', 'refunds__items'), pk=sale_id)
    except DatabaseError:
        logger.exception('Archive database unavailable')
        messages.error(request, "The archive database isn't reachable right now.")
        return redirect('sales:sale_history')
    tenant = Tenant.objects.filter(id=sale.tenant_id).first()
    vatable_sale = sale.total / Decimal('1.12')
    return render(request, 'sales/receipt.html', {
        'sale': sale,
        'tenant': tenant,
        'vatable_sale': vatable_sale,
        'vat_amount': sale.total - vatable_sale,
        'archived': True,
    })

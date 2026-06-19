from django.contrib import messages
from accounts.decorators import manager_or_admin_required, pos_login_required
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404

from customers.models import Customer
from products.models import Product, Category
from .models import Sale, SaleItem
from django.db import transaction
from django.db.models import F

from django.db.models import Value, IntegerField, Q as DQ

import json
from django.utils import timezone
from django.db.models import Sum, Count
from django.db.models.functions import TruncDate, Coalesce
from datetime import timedelta

from tenants.models import Tenant
from django.http import JsonResponse

from decimal import Decimal


# ─── Dashboard ───────────────────────────────────────────────
@pos_login_required
def dashboard(request):

    today = timezone.localdate()
    seven_days_ago = today - timedelta(days=6)

    # ── Today's stats ─────────────────────────────────────────────
    todays_sales = Sale.objects.filter(
        status='completed',
        created_at__date=today
    ).prefetch_related('items')

    total_today = sum(s.total for s in todays_sales)
    avg_sale    = (total_today / len(todays_sales)) if todays_sales else 0

    # ── Recent sales table (last 10 completed today) ───────────────
    recent_sales = Sale.objects.filter(
        status='completed',
        created_at__date=today
    ).order_by('-created_at')[:10]

    # ── Revenue by day (last 7 days) ──────────────────────────────
    daily_revenue = (
        SaleItem.objects
        .filter(
            sale__status='completed',
            sale__created_at__date__gte=seven_days_ago,
        )
        .annotate(day=TruncDate('sale__created_at'))
        .values('day')
        .annotate(revenue=Sum('unit_price') * 1)  # placeholder
        .order_by('day')
    )

    # Build a proper day-by-day revenue using raw aggregation
    from django.db.models import F as Fexpr
    daily_qs = (
        SaleItem.objects
        .filter(sale__status='completed', sale__created_at__date__gte=seven_days_ago)
        .annotate(day=TruncDate('sale__created_at'))
        .values('day')
        .annotate(revenue=Sum(Fexpr('quantity') * Fexpr('unit_price')))
        .annotate(txns=Count('sale', distinct=True))
        .order_by('day')
    )

    # Fill in missing days with 0
    daily_map = {entry['day']: entry for entry in daily_qs}
    chart_days, chart_revenue, chart_txns = [], [], []
    for i in range(7):
        day = seven_days_ago + timedelta(days=i)
        entry = daily_map.get(day)
        chart_days.append(day.strftime('%b %d'))
        chart_revenue.append(float(entry['revenue']) if entry else 0)
        chart_txns.append(entry['txns'] if entry else 0)

    # ── Top 5 products by revenue ─────────────────────────────────
    from django.db.models import F as Fexpr
    top_products = (
        SaleItem.objects
        .filter(sale__status='completed')
        .values('product__name')
        .annotate(revenue=Sum(Fexpr('quantity') * Fexpr('unit_price')))
        .order_by('-revenue')[:5]
    )
    top_product_labels = [p['product__name'] for p in top_products]
    top_product_values = [float(p['revenue']) for p in top_products]

    # ── Top 5 products by units sold ─────────────────────────────
    top_units = (
        SaleItem.objects
        .filter(sale__status='completed')
        .values('product__name')
        .annotate(units=Sum('quantity'))
        .order_by('-units')[:5]
    )
    top_units_labels = [p['product__name'] for p in top_units]
    top_units_values = [p['units'] for p in top_units]

    # ── Low stock products (stock <= 5) ───────────────────────────
    from products.models import Product
    low_stock = (
        Product.objects
        .filter(is_active=True, stock__lte=5)
        .order_by('stock')
    )

    # ── Cashier performance (all time) ────────────────────────────
    cashier_stats = (
        Sale.objects
        .filter(status='completed')
        .values('cashier__username')
        .annotate(
            sales_count=Count('id'),
            revenue=Sum(
                SaleItem.objects.filter(sale=Fexpr('id'))
                .values('sale')
                .annotate(t=Sum(Fexpr('quantity') * Fexpr('unit_price')))
                .values('t')[:1]
            )
        )
    )

    # Simpler cashier stats using Python
    from django.contrib.auth.models import User
    cashier_data = []
    tenant_cashier_ids = (
        Sale.objects
        .filter(status='completed')  # TenantManager scopes this
        .values_list('cashier_id', flat=True)
        .distinct()
    )
    cashiers = User.objects.filter(pk__in=tenant_cashier_ids)
    for cashier in cashiers:
        sales = Sale.objects.filter(status='completed', cashier=cashier).prefetch_related('items')
        rev = sum(s.total for s in sales)
        cashier_data.append({
            'username': cashier.username,
            'sales_count': sales.count(),
            'revenue': rev,
        })
    cashier_data.sort(key=lambda x: x['revenue'], reverse=True)
    max_cashier_revenue = cashier_data[0]['revenue'] if cashier_data else 1

    # ── Sale status counts ────────────────────────────────────────
    status_counts = {
        'completed': Sale.objects.filter(status='completed').count(),
        'refunded':  Sale.objects.filter(status='refunded').count(),
        'pending':   Sale.objects.filter(status='pending').count(),
    }

    # ── Refund rate ───────────────────────────────────────────────
    total_sales_count = status_counts['completed'] + status_counts['refunded']
    refund_rate = round(
        (status_counts['refunded'] / total_sales_count * 100), 1
    ) if total_sales_count else 0

    # ── Low stock count ───────────────────────────────────────────
    low_stock_count = low_stock.count()

    return render(request, 'sales/dashboard.html', {
        # Today
        'total_today':        total_today,
        'avg_sale':           avg_sale,
        'recent_sales':       recent_sales,
        'sales_count_today':  len(todays_sales),

        # Refund & stock summary
        'refund_rate':        refund_rate,
        'total_sales_count':  total_sales_count,
        'low_stock_count':    low_stock_count,

        # Charts (JSON for JS)
        'chart_days':         json.dumps(chart_days),
        'chart_revenue':      json.dumps(chart_revenue),
        'chart_txns':         json.dumps(chart_txns),
        'top_product_labels': json.dumps(top_product_labels),
        'top_product_values': json.dumps(top_product_values),
        'top_units_labels':   json.dumps(top_units_labels),
        'top_units_values':   json.dumps(top_units_values),

        # Tables/lists
        'low_stock':          low_stock,
        'cashier_data':       cashier_data,
        'max_cashier_revenue': max_cashier_revenue,
        'status_counts':      status_counts,
    })

# ─── Create Sale (POS) ───────────────────────────────────────
@pos_login_required
def create_sale(request):
    products = (
        Product.objects
        .filter(is_active=True)
        .select_related('category')
        .annotate(
            total_sold=Coalesce(
                Sum('saleitem__quantity', filter=DQ(saleitem__sale__status='completed')),
                Value(0), output_field=IntegerField()
            )
        )
        .order_by('-total_sold')[:24]
    )
    customers = Customer.objects.all()
    categories = Category.objects.all()

    # ── Check for preserved cart from session (after redirect) ──
    preserved_cart = request.session.pop('preserved_cart', None)
    preserved_customer = request.session.pop('preserved_customer', None)
    preserved_cash_tendered = request.session.pop('preserved_cash_tendered', None)
    preserved_payment_method = request.session.pop('preserved_payment_method', None)
    preserved_reference_number = request.session.pop('preserved_reference_number', None)

    if request.method == 'POST':
        customer_id = request.POST.get('customer') or None
        status = request.POST.get('status', 'completed')
        cash_tendered = request.POST.get('cash_tendered') or None
        change_given = request.POST.get('change_given') or None
        payment_method = request.POST.get('payment_method', 'cash')
        reference_number = request.POST.get('reference_number') or None

        customer = None
        if customer_id:
            try:
                customer = Customer.objects.get(pk=customer_id)
            except Customer.DoesNotExist:
                pass

        total_forms = int(request.POST.get('items-TOTAL_FORMS', 0))
        if total_forms == 0:
            messages.error(request, 'No valid items in the sale.')
            return redirect('sales:create_sale')

        # ── Build complete preserved cart from ALL POST items ──
        preserved_cart_data = []
        stock_errors = []

        for i in range(total_forms):
            product_id = request.POST.get(f'items-{i}-product')
            quantity = request.POST.get(f'items-{i}-quantity')
            unit_price = request.POST.get(f'items-{i}-unit_price')

            if product_id and quantity and unit_price:
                try:
                    product = Product.objects.get(pk=product_id, is_active=True)
                    qty = int(quantity)

                    has_stock_error = False
                    if status == 'completed' and product.stock < qty:
                        stock_errors.append({
                            'name': product.name,
                            'requested': qty,
                            'available': product.stock,
                        })
                        has_stock_error = True

                    preserved_cart_data.append({
                        'product_id': product_id,
                        'name': product.name,
                        'quantity': qty,
                        'unit_price': float(unit_price),
                        'stock': product.stock,
                        'has_error': has_stock_error,
                    })

                except (Product.DoesNotExist, ValueError):
                    pass

        # ── If stock errors found, store in session and redirect ──
        if stock_errors:
            if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                for err in stock_errors:
                    messages.error(
                        request,
                        f'"{err["name"]}" — requested {err["requested"]}, only {err["available"]} in stock. '
                        f'Reduce quantity or remove from cart.'
                    )

            # Store cart data in session, then redirect to GET
            request.session['preserved_cart'] = preserved_cart_data
            request.session['preserved_customer'] = customer_id
            request.session['preserved_cash_tendered'] = cash_tendered
            request.session['preserved_payment_method'] = payment_method
            request.session['preserved_reference_number'] = reference_number

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'reload': True})
            return redirect('sales:create_sale')

        # ── No stock errors — safe to create sale ──
        try:
            with transaction.atomic():
                sale = Sale.objects.create(
                    customer=customer,
                    cashier=request.user,
                    status=status,
                    payment_method=payment_method,
                    reference_number=reference_number if status == 'completed' else None,
                    cash_tendered=cash_tendered if status == 'completed' else None,
                    change_given=change_given if status == 'completed' else None,
                )

                has_items = False

                for i in range(total_forms):
                    product_id = request.POST.get(f'items-{i}-product')
                    quantity = request.POST.get(f'items-{i}-quantity')
                    unit_price = request.POST.get(f'items-{i}-unit_price')

                    if not product_id or not quantity or not unit_price:
                        continue

                    try:
                        quantity = int(quantity)
                        if quantity <= 0:
                            continue

                        product = Product.objects.select_for_update().get(pk=product_id, is_active=True)
                        unit_price = product.price

                        if status == 'completed':
                            Product.objects.filter(pk=product.pk).update(stock=F('stock') - quantity)

                        SaleItem.objects.create(
                            sale=sale,
                            product=product,
                            quantity=quantity,
                            unit_price=unit_price,
                        )
                        has_items = True

                    except Product.DoesNotExist:
                        messages.error(request, f'Product no longer exists or is inactive.')
                        raise
                    except ValueError:
                        continue

                if not has_items:
                    messages.error(request, 'No valid items in the sale.')
                    raise ValueError('no items')

        except Exception:
            messages.error(request, 'Sale could not be completed. Please try again.')

            # Store cart data in session and redirect
            request.session['preserved_cart'] = preserved_cart_data
            request.session['preserved_customer'] = customer_id
            request.session['preserved_cash_tendered'] = cash_tendered
            request.session['preserved_payment_method'] = payment_method
            request.session['preserved_reference_number'] = reference_number

            return redirect('sales:create_sale')

        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        if status == 'pending':
            if not is_ajax:
                messages.success(request, f'Sale #{sale.pk} saved as pending.')
            if is_ajax:
                return JsonResponse({'success': True, 'redirect': '/sales/pending/'})
            return redirect('sales:pending_sales')
        else:
            if not is_ajax:
                messages.success(request, f'Sale #{sale.pk} completed successfully.')
            if is_ajax:
                return JsonResponse({'success': True, 'sale_id': sale.pk})
            return redirect('sales:receipt', sale_id=sale.pk)

    # GET — render the POS (with optional preserved cart from session)
    return render(request, 'sales/create_sale.html', {
        'products': products,
        'customers': customers,
        'categories': categories,
        'preserved_cart': json.dumps(preserved_cart) if preserved_cart else None,
        'preserved_customer': preserved_customer,
        'preserved_cash_tendered': preserved_cash_tendered,
        'preserved_payment_method': preserved_payment_method,
        'preserved_reference_number': preserved_reference_number,
    })

# ─── Pending Sales ─────────────────────────────────────────────

@pos_login_required
def pending_sales(request):
    """List all pending sales (admin sees all, cashier sees only theirs)"""
    if request.user.is_superuser or request.user.profile.can_access_user_management:
        pending = Sale.objects.filter(status='pending').order_by('-created_at')
    else:
        pending = Sale.objects.filter(status='pending', cashier=request.user).order_by('-created_at')

    return render(request, 'sales/pending_sales.html', {'pending_sales': pending})


@pos_login_required
def resume_sale(request, pk):
    sale = get_object_or_404(Sale, pk=pk)

    if sale.status != 'pending':
        messages.error(request, f'Sale #{pk} is no longer pending.')
        return redirect('sales:pending_sales')

    if not (
            request.user.is_superuser or request.user.profile.can_access_user_management or sale.cashier == request.user):
        messages.error(request, 'Permission denied.')
        return redirect('sales:pending_sales')

    products = (
        Product.objects
        .filter(is_active=True)
        .select_related('category')
        .annotate(
            total_sold=Coalesce(
                Sum('saleitem__quantity', filter=DQ(saleitem__sale__status='completed')),
                Value(0), output_field=IntegerField()
            )
        )
        .order_by('-total_sold')[:24]
    )
    customers = Customer.objects.all()
    categories = Category.objects.all()

    # ── Check for preserved cart from session (after redirect) ──
    preserved_cart = request.session.pop('preserved_cart', None)
    preserved_customer = request.session.pop('preserved_customer', None)
    preserved_cash_tendered = request.session.pop('preserved_cash_tendered', None)
    preserved_payment_method = request.session.pop('preserved_payment_method', None)
    preserved_reference_number = request.session.pop('preserved_reference_number', None)

    if request.method == 'POST':
        customer_id = request.POST.get('customer') or None
        status = request.POST.get('status', 'completed')
        cash_tendered = request.POST.get('cash_tendered') or None
        change_given = request.POST.get('change_given') or None
        payment_method = request.POST.get('payment_method', 'cash')
        reference_number = request.POST.get('reference_number') or None

        customer = None
        if customer_id:
            try:
                customer = Customer.objects.get(pk=customer_id)
            except Customer.DoesNotExist:
                pass

        total_forms = int(request.POST.get('items-TOTAL_FORMS', 0))
        if total_forms == 0:
            messages.error(request, 'No valid items in the sale.')
            return redirect('sales:resume_sale', pk=pk)

        # ── Build complete preserved cart from ALL POST items ──
        preserved_cart_data = []
        stock_errors = []

        for i in range(total_forms):
            product_id = request.POST.get(f'items-{i}-product')
            quantity = request.POST.get(f'items-{i}-quantity')
            unit_price = request.POST.get(f'items-{i}-unit_price')

            if product_id and quantity and unit_price:
                try:
                    product = Product.objects.get(pk=product_id, is_active=True)
                    qty = int(quantity)

                    has_stock_error = False
                    if status == 'completed' and product.stock < qty:
                        stock_errors.append({
                            'name': product.name,
                            'requested': qty,
                            'available': product.stock,
                        })
                        has_stock_error = True

                    preserved_cart_data.append({
                        'product_id': product_id,
                        'name': product.name,
                        'quantity': qty,
                        'unit_price': float(unit_price),
                        'stock': product.stock,
                        'has_error': has_stock_error,
                    })

                except (Product.DoesNotExist, ValueError):
                    pass

        # ── If stock errors found, store in session and redirect ──
        if stock_errors:
            if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                for err in stock_errors:
                    messages.error(
                        request,
                        f'"{err["name"]}" — requested {err["requested"]}, only {err["available"]} in stock. '
                        f'Reduce quantity or remove from cart.'
                    )

            request.session['preserved_cart'] = preserved_cart_data
            request.session['preserved_customer'] = customer_id
            request.session['preserved_cash_tendered'] = cash_tendered
            request.session['preserved_payment_method'] = payment_method
            request.session['preserved_reference_number'] = reference_number
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'reload': True})
            return redirect('sales:create_sale')

        # ── No stock errors — safe to complete sale ──
        try:
            with transaction.atomic():
                # Remove old items from this pending sale (no stock was deducted)
                sale.items.all().delete()

                # Update the existing sale record
                sale.customer = customer
                sale.status = status
                sale.payment_method = payment_method
                sale.reference_number = reference_number if status == 'completed' else None
                sale.cash_tendered = cash_tendered if status == 'completed' else None
                sale.change_given = change_given if status == 'completed' else None

                # ── FIX: Update created_at to now when completing ──
                if status == 'completed':
                    sale.created_at = timezone.now()

                sale.save()

                has_items = False

                for i in range(total_forms):
                    product_id = request.POST.get(f'items-{i}-product')
                    quantity = request.POST.get(f'items-{i}-quantity')
                    unit_price = request.POST.get(f'items-{i}-unit_price')

                    if not product_id or not quantity or not unit_price:
                        continue

                    try:
                        quantity = int(quantity)
                        if quantity <= 0:
                            continue

                        product = Product.objects.select_for_update().get(pk=product_id)

                        if status == 'completed':
                            Product.objects.filter(pk=product.pk).update(stock=F('stock') - quantity)

                        SaleItem.objects.create(
                            sale=sale,
                            product=product,
                            quantity=quantity,
                            unit_price=unit_price,
                        )
                        has_items = True

                    except Product.DoesNotExist:
                        messages.error(request, 'A product in the sale no longer exists.')
                        raise
                    except ValueError:
                        continue

                if not has_items:
                    messages.error(request, 'No valid items in the sale.')
                    raise ValueError('no items')

        except Exception:
            messages.error(request, 'Sale could not be completed. Please try again.')

            request.session['preserved_cart'] = preserved_cart_data
            request.session['preserved_customer'] = customer_id
            request.session['preserved_cash_tendered'] = cash_tendered
            request.session['preserved_payment_method'] = payment_method
            request.session['preserved_reference_number'] = reference_number

            return redirect('sales:resume_sale', pk=pk)

        if status == 'pending':
            if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                messages.success(request, f'Sale #{sale.pk} updated and kept on hold.')
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'redirect': '/sales/pending/'})
            return redirect('sales:pending_sales')
        else:
            if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                messages.success(request, f'Sale #{sale.pk} completed successfully.')
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'sale_id': sale.pk})
            return redirect('sales:receipt', sale_id=sale.pk)

    # GET — render the POS with pending sale + optional preserved cart from session
    return render(request, 'sales/create_sale.html', {
        'products': products,
        'customers': customers,
        'categories': categories,
        'pending_sale': sale,
        'preserved_cart': json.dumps(preserved_cart) if preserved_cart else None,
        'preserved_customer': preserved_customer,
        'preserved_cash_tendered': preserved_cash_tendered,
        'preserved_payment_method': preserved_payment_method,
        'preserved_reference_number': preserved_reference_number,
    })


@pos_login_required
def delete_pending(request, pk):
    """Delete a pending sale"""
    sale = get_object_or_404(Sale, pk=pk, status='pending')

    if not (
            request.user.is_superuser or request.user.profile.can_access_user_management or sale.cashier == request.user):
        messages.error(request, 'Permission denied.')
        return redirect('sales:pending_sales')

    if request.method == 'POST':
        sale.delete()
        messages.success(request, 'Pending sale deleted.')
        return redirect('sales:pending_sales')

    return render(request, 'sales/delete_pending.html', {'sale': sale})

# ─── Sale History ─────────────────────────────────────────────
from django.core.paginator import Paginator

@pos_login_required
def sale_history(request):
    sales = Sale.objects.filter(status__in=['completed', 'refunded']).order_by('-created_at')

    # Search filter
    query = request.GET.get('q', '')
    if query:
        sales = sales.filter(
            Q(customer__name__icontains=query) |
            Q(cashier__username__icontains=query) |
            Q(pk__icontains=query) |
            Q(status__icontains=query)
        )

    # Date filter
    date_from = request.GET.get('date_from', '')
    date_to   = request.GET.get('date_to', '')
    if date_from:
        sales = sales.filter(created_at__date__gte=date_from)
    if date_to:
        sales = sales.filter(created_at__date__lte=date_to)

    paginator = Paginator(sales, 12)
    page      = request.GET.get('page')
    sales     = paginator.get_page(page)

    return render(request, 'sales/history.html', {
        'sales':     sales,
        'query':     query,
        'date_from': date_from,
        'date_to':   date_to,
    })

# ─── Refund/Void ─────────────────────────────────────────────

@manager_or_admin_required
def refund_sale(request, pk):
    sale = get_object_or_404(Sale, pk=pk)

    if sale.status == 'refunded':
        messages.error(request, f'Sale #{sale.pk} is already refunded.')
        return redirect('sales:sale_history')

    if request.method == 'POST':
        with transaction.atomic():

            for item in sale.items.select_related('product'):
                Product.objects.filter(pk=item.product_id).update(
                    stock=F('stock') + item.quantity
                )

            sale.status = 'refunded'
            sale.save()

        messages.success(request, f'Sale #{sale.pk} has been refunded and stock restored.')
        return redirect('sales:sale_history')

    return render(request, 'sales/refund_confirm.html', {'sale': sale})

# ─── Receipt ─────────────────────────────────────────────

@pos_login_required
def receipt(request, sale_id):
    sale = get_object_or_404(Sale, pk=sale_id)

    try:
        tenant_id = request.session.get('tenant_id')
        tenant = Tenant.objects.get(id=tenant_id)
    except Exception:
        return redirect('/accounts/login/')

    vatable_sale = sale.total / Decimal('1.12')
    vat_amount = sale.total - vatable_sale

    return render(request, 'sales/receipt.html', {
        'sale': sale,
        'tenant': tenant,
        'vatable_sale': vatable_sale,
        'vat_amount': vat_amount,
    })
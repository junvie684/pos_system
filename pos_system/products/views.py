from django.db.models import Q, Count
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .models import Product, Category
from .forms import ProductForm
from django.core.paginator import Paginator
from django.contrib import messages
from accounts.decorators import manager_or_admin_required



@manager_or_admin_required
def product_list(request):
    search = request.GET.get('q', '')
    show_inactive = request.GET.get('show_inactive') == '1'

    if show_inactive:
        products = Product.objects.filter(is_active=False).select_related('category').order_by('name')
    else:
        products = Product.objects.filter(is_active=True).select_related('category').order_by('name')

    if search:
        products = products.filter(
            Q(name__icontains=search) |
            Q(category__name__icontains=search)
        )

    paginator = Paginator(products, 13)
    page_obj = paginator.get_page(request.GET.get('page'))
    categories = Category.objects.order_by('name')

    return render(request, 'products/product_list.html', {
        'products': page_obj,
        'page_obj': page_obj,
        'search': search,
        'categories': categories,
        'show_inactive': show_inactive,
    })


@manager_or_admin_required
def add_product(request):
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'product': {
                        'pk': product.pk,
                        'name': product.name,
                        'category': product.category.name if product.category else None,
                        'category_id': product.category.pk if product.category else None,
                        'price': str(product.price),
                        'stock': product.stock,
                    }
                })
            messages.success(request, 'Product added successfully.')
            return redirect('products:product_list')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'errors': form.errors.get_json_data()})
        messages.error(request, 'Failed to add product.')
        return redirect('products:product_list')
    return redirect('products:product_list')


@manager_or_admin_required
def edit_product(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'product': {
                        'pk': product.pk,
                        'name': product.name,
                        'category': product.category.name if product.category else None,
                        'category_id': product.category.pk if product.category else None,
                        'price': str(product.price),
                        'stock': product.stock,
                        'barcode': product.barcode or '',
                        'is_active': product.is_active,
                    }
                })
            messages.success(request, 'Product updated successfully.')
            return redirect('products:product_list')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'errors': form.errors.get_json_data()})
        messages.error(request, 'Failed to update product.')
        return redirect('products:product_list')
    return redirect('products:product_list')


@manager_or_admin_required
def delete_product(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        name = product.name
        product.is_active = False  # ← SOFT DELETE: DEACTIVATE INSTEAD
        product.save()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'name': name})
        messages.success(request, f'Product "{name}" deactivated.')
        return redirect('products:product_list')
    return redirect('products:product_list')

@manager_or_admin_required
def reactivate_product(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        product.is_active = True
        product.save()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'name': product.name})
        messages.success(request, f'Product "{product.name}" reactivated.')
        return redirect('products:product_list')
    return redirect('products:product_list')


# ─── Categories ──────────────────────────────────────────────
@manager_or_admin_required
def category_list(request):
    categories = Category.objects.annotate(product_count=Count('product')).order_by('name')
    return render(request, 'products/category_list.html', {'categories': categories})


@manager_or_admin_required
def add_category(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            return JsonResponse({'ok': False, 'error': 'Category name is required.'})
        cat, created = Category.objects.get_or_create(name=name)
        if created:
            return JsonResponse({'ok': True, 'id': cat.pk, 'name': cat.name})
        return JsonResponse({'ok': False, 'error': 'Category already exists.'})
    return JsonResponse({'ok': False, 'error': 'Invalid request.'})


@manager_or_admin_required
def edit_category(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            return JsonResponse({'ok': False, 'error': 'Category name is required.'})
        category.name = name
        category.save()
        return JsonResponse({'ok': True, 'id': category.pk, 'name': category.name})
    return JsonResponse({'ok': False, 'error': 'Invalid request.'})


@manager_or_admin_required
def delete_category(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if request.method == 'POST':
        name = category.name
        category.delete()
        return JsonResponse({'ok': True, 'name': name})
    return JsonResponse({'ok': False, 'error': 'Invalid request.'})


# ─── API: product search (used in create_sale) ───────────────
@login_required
def product_search_api(request):
    q = request.GET.get('q', '')
    products = Product.objects.filter(is_active=True).filter(  # ← ONLY ACTIVE PRODUCTS
        Q(name__icontains=q) | Q(category__name__icontains=q)
    ).select_related('category')[:20]
    data = [{'id': p.pk, 'name': p.name, 'price': str(p.price),
              'stock': p.stock, 'category': p.category.name if p.category else ''} for p in products]
    return JsonResponse({'products': data})


# ─── Product Sale History ───────────────

import csv
from datetime import datetime, timedelta
from django.db.models import Sum, Count, F, Q
from django.db.models.functions import TruncDate, TruncMonth
from django.shortcuts import render, redirect, get_object_or_404

from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.contrib import messages
from accounts.decorators import manager_or_admin_required
from .models import Product, Category
from .forms import ProductForm

from sales.models import SaleItem


@manager_or_admin_required
def product_sales_history(request, product_id):
    product = get_object_or_404(Product, pk=product_id)

    # --- Date range filter ---
    today = datetime.now().date()
    default_from = today - timedelta(days=30)

    date_from_str = request.GET.get('date_from')
    date_to_str = request.GET.get('date_to')
    group_by = request.GET.get('group_by', 'daily')  # 'daily' or 'monthly'

    try:
        date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date() if date_from_str else default_from
    except ValueError:
        date_from = default_from

    try:
        date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date() if date_to_str else today
    except ValueError:
        date_to = today

    # Base queryset
    items = SaleItem.objects.filter(
        product=product,
        sale__status='completed',
        sale__created_at__date__gte=date_from,
        sale__created_at__date__lte=date_to
    )

    # Group by date
    if group_by == 'monthly':
        history = items.annotate(
            period=TruncMonth('sale__created_at')
        ).values('period').annotate(
            units_sold=Sum('quantity'),
            revenue=Sum(F('quantity') * F('unit_price')),
            transactions=Count('sale', distinct=True)
        ).order_by('period')

        for entry in history:
            entry['label'] = entry['period'].strftime('%b %Y')
    else:
        history = items.annotate(
            period=TruncDate('sale__created_at')
        ).values('period').annotate(
            units_sold=Sum('quantity'),
            revenue=Sum(F('quantity') * F('unit_price')),
            transactions=Count('sale', distinct=True)
        ).order_by('period')

        for entry in history:
            entry['label'] = entry['period'].strftime('%b %d, %Y')

    # Calculate averages per row
    for entry in history:
        entry['avg_per_sale'] = entry['units_sold'] / entry['transactions'] if entry['transactions'] > 0 else 0

    # Totals
    totals = items.aggregate(
        total_units=Sum('quantity'),
        total_revenue=Sum(F('quantity') * F('unit_price')),
        total_transactions=Count('sale', distinct=True)
    )

    # Calculate total average
    totals['avg_per_sale'] = totals['total_units'] / totals['total_transactions'] if totals[
                                                                                         'total_transactions'] > 0 else 0

    # --- CSV Export ---
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response[
            'Content-Disposition'] = f'attachment; filename="product_history_{product.id}_{date_from}_{date_to}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Period', 'Units Sold', 'Revenue', 'Transactions', 'Avg per Sale'])
        for entry in history:
            writer.writerow([
                entry['label'],
                entry['units_sold'],
                entry['revenue'],
                entry['transactions'],
                round(entry['avg_per_sale'], 1)
            ])
        writer.writerow([])
        writer.writerow([
            'TOTAL',
            totals['total_units'],
            totals['total_revenue'],
            totals['total_transactions'],
            round(totals['avg_per_sale'], 1)
        ])
        return response

    return render(request, 'products/product_history.html', {
        'product': product,
        'history': history,
        'totals': totals,
        'date_from': date_from.strftime('%Y-%m-%d'),
        'date_to': date_to.strftime('%Y-%m-%d'),
        'group_by': group_by,
        'has_data': len(history) > 0,
    })
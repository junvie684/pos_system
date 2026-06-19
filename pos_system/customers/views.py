from django.shortcuts import render, redirect, get_object_or_404
from accounts.decorators import pos_login_required
from django.http import JsonResponse
from .models import Customer
from .forms import CustomerForm


@pos_login_required
def customer_list(request):
    customers = Customer.objects.all().order_by('name')
    return render(request, 'customers/customer_list.html', {'customers': customers})


@pos_login_required
def add_customer(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            customer = form.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'customer': {
                        'pk': customer.pk,
                        'name': customer.name,
                        'email': customer.email or '—',
                        'phone': customer.phone or '—',
                        'created_at': customer.created_at.strftime('%b %d, %Y'),
                    }
                })
            return redirect('customers:customer_list')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'errors': form.errors.get_json_data()})
    return redirect('customers:customer_list')


@pos_login_required
def edit_customer(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'customer': {
                        'pk': customer.pk,
                        'name': customer.name,
                        'email': customer.email or '—',
                        'phone': customer.phone or '—',
                    }
                })
            return redirect('customers:customer_list')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'errors': form.errors.get_json_data()})
    return redirect('customers:customer_list')


@pos_login_required
def delete_customer(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        name = customer.name
        customer.delete()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'name': name})
        return redirect('customers:customer_list')
    return redirect('customers:customer_list')
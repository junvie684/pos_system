from django.shortcuts import render
from django.utils import timezone
from sales.models import Sale

def daily_report(request):
    today = timezone.now().date()
    sales = Sale.objects.filter(created_at__date=today, status='completed')
    total_revenue = sum(sale.total for sale in sales)
    context = {
        'sales': sales,
        'total_revenue': total_revenue,
        'count': sales.count(),
    }
    return render(request, 'reports/daily.html', context)
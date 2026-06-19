from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import JsonResponse
from django.db import transaction
from django.views.decorators.http import require_http_methods
import jwt
import datetime
from django.conf import settings

from .forms import TenantRegistrationForm
from .models import Tenant
from accounts.models import UserProfile


@require_http_methods(['GET', 'POST'])
def register_store(request):
    """
    Public endpoint — anyone can register a new store.
    Creates: Tenant + superuser owner + UserProfile in one transaction.
    """
    form = TenantRegistrationForm(request.POST or None)

    if request.method == 'POST':
        if form.is_valid():
            try:
                with transaction.atomic():
                    # 1. Create the tenant (store)
                    tenant = Tenant.objects.create(
                        name=form.cleaned_data['store_name'],
                        slug=form.cleaned_data['store_slug'],
                        owner=form.cleaned_data['email'],
                        address=form.cleaned_data.get('store_address', ''),
                        phone=form.cleaned_data.get('store_phone', ''),
                        tin=form.cleaned_data.get('store_tin', ''),
                        is_active=True,
                    )

                    # 2. Create the owner user
                    owner = User.objects.create_user(
                        username=form.cleaned_data['username'],
                        email=form.cleaned_data['email'],
                        password=form.cleaned_data['password'],
                        is_staff=True,
                        is_superuser=True,
                    )

                    # 3. Create owner's profile — full access
                    UserProfile.objects.create(
                        user=owner,
                        tenant_id=tenant.id,
                        can_access_products=True,
                        can_access_categories=True,
                        can_access_reports=True,
                        can_access_user_management=True,
                        can_access_pending_sales=True,
                        can_access_shift_report=True,
                    )

            except Exception as e:
                messages.error(request, 'Registration failed. Please try again.')
                return render(request, 'tenants/register.html', {'form': form})

            messages.success(
                request,
                f'Store "{tenant.name}" registered! You can now log in.'
            )
            return redirect('/accounts/login/')

        # AJAX support
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'errors': form.errors.get_json_data()})

    return render(request, 'tenants/register.html', {'form': form})


@require_http_methods(['POST'])
def store_login(request):
    """
    Issues a JWT containing tenant_id.
    POST { username, password }
    """
    import json
    try:
        body = json.loads(request.body)
    except Exception:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    username = body.get('username', '').strip()
    password = body.get('password', '').strip()

    if not username or not password:
        return JsonResponse({'error': 'Username and password required.'}, status=400)

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return JsonResponse({'error': 'Invalid credentials.'}, status=401)

    if not user.check_password(password):
        return JsonResponse({'error': 'Invalid credentials.'}, status=401)

    if not user.is_active:
        return JsonResponse({'error': 'Account is disabled.'}, status=403)

    # Get this user's tenant via their profile
    try:
        profile = UserProfile.objects.get(user=user)
    except UserProfile.DoesNotExist:
        return JsonResponse({'error': 'No store linked to this account.'}, status=403)

    try:
        tenant = Tenant.objects.get(id=profile.tenant_id, is_active=True)
    except Tenant.DoesNotExist:
        return JsonResponse({'error': 'Store not found or inactive.'}, status=403)

    # Issue JWT
    payload = {
        'user_id'    : user.id,
        'username'   : user.username,
        'tenant_id'  : str(tenant.id),
        'store_name' : tenant.name,
        'store_slug' : tenant.slug,
        'is_superuser': user.is_superuser,
        'is_staff'   : user.is_staff,
        'exp'        : datetime.datetime.utcnow() + datetime.timedelta(hours=8),
    }

    token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

    return JsonResponse({
        'token'     : token,
        'store'     : tenant.name,
        'username'  : user.username,
        'expires_in': '8 hours',
    })


def store_list(request):
    """
    Superadmin only — list all registered stores.
    Protect this in production with IP allowlist or admin-only access.
    """
    if not request.user.is_authenticated or not request.user.is_superuser:
        return JsonResponse({'error': 'Forbidden'}, status=403)

    stores = Tenant.objects.all().order_by('name').values(
        'id', 'name', 'slug', 'owner', 'is_active', 'created_at'
    )
    return JsonResponse({'stores': list(stores)}, json_dumps_params={'default': str})
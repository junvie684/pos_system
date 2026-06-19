from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse

from .decorators import platform_admin_required, platform_permission_required
from .models import Tenant
from accounts.models import UserProfile
from sales.models import Sale
from products.models import Product


# ─── Helper: build profile permissions from User flags ───────
def _permissions_from_user(user, is_owner=False):
    """
    Single source of truth for deriving profile permission flags from
    Django's built-in is_staff / is_superuser flags.
    Pass is_owner=True when creating the first admin user for a store —
    that user always gets user_management access regardless of is_superuser.
    Mirrors the same helper in views.py.
    """
    return {
        'can_access_products'       : user.is_staff or user.is_superuser,
        'can_access_categories'     : user.is_staff or user.is_superuser,
        'can_access_reports'        : user.is_staff or user.is_superuser,
        'can_access_user_management': user.is_superuser or is_owner,
        'can_access_pending_sales'  : user.is_staff or user.is_superuser,
        'can_access_shift_report'   : user.is_staff or user.is_superuser,
    }


# ═══════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════

@platform_permission_required('tenants.view_tenant')
def dashboard(request):
    tenants = Tenant.objects.all().order_by('name')

    stats = []
    for tenant in tenants:
        user_count    = UserProfile.all_objects.filter(tenant_id=tenant.id).count()
        sale_count    = Sale.all_objects.filter(tenant_id=tenant.id).count()
        product_count = Product.all_objects.filter(tenant_id=tenant.id).count()
        stats.append({
            'tenant'       : tenant,
            'user_count'   : user_count,
            'sale_count'   : sale_count,
            'product_count': product_count,
        })

    return render(request, 'platform_admin/dashboard.html', {
        'stats'        : stats,
        'total_stores' : tenants.count(),
        'active_stores': tenants.filter(is_active=True).count(),
    })


# ═══════════════════════════════════════════════════════════════
# CREATE STORE
# ═══════════════════════════════════════════════════════════════

@platform_permission_required('tenants.add_tenant')
def create_store(request):
    if request.method == 'POST':
        name           = request.POST.get('name', '').strip()
        slug           = request.POST.get('slug', '').strip()
        owner_email    = request.POST.get('owner_email', '').strip()
        owner_password = request.POST.get('owner_password', '').strip()

        errors = {}
        if not name:
            errors['name'] = 'Store name is required.'
        if not owner_email:
            errors['owner_email'] = 'Owner email is required.'
        if not owner_password:
            errors['owner_password'] = 'Owner password is required.'
        else:
            # Validate password strength — mirrors add_store_user
            try:
                validate_password(owner_password)
            except ValidationError as e:
                errors['owner_password'] = ' '.join(e.messages)
        if slug and Tenant.objects.filter(slug=slug).exists():
            errors['slug'] = 'Slug already exists.'

        if errors:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': errors})
            for field, msg in errors.items():
                messages.error(request, msg)
            return redirect('platform_admin:dashboard')

        with transaction.atomic():
            tenant = Tenant.objects.create(
                name=name,
                slug=slug or None,
                owner=owner_email,
                is_active=True,
            )

            # Derive a unique username from the email prefix
            base_username = owner_email.split('@')[0]
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            owner = User.objects.create_user(
                username=username,
                email=owner_email,
                password=owner_password,
                is_staff=True,
            )

            UserProfile.objects.create(
                user=owner,
                tenant_id=tenant.id,
                **_permissions_from_user(owner, is_owner=True),
            )

        messages.success(request, f'Store "{name}" created successfully.')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        return redirect('platform_admin:dashboard')

    return redirect('platform_admin:dashboard')


# ═══════════════════════════════════════════════════════════════
# STORE DETAIL
# ═══════════════════════════════════════════════════════════════

@platform_permission_required('tenants.view_tenant')
def store_detail(request, tenant_id):
    tenant   = get_object_or_404(Tenant, id=tenant_id)
    profiles = UserProfile.objects.filter(  # ← Use objects, not all_objects
        tenant_id=tenant.id
    ).select_related('user').order_by('user__username')

    return render(request, 'platform_admin/store_detail.html', {
        'tenant'  : tenant,
        'profiles': profiles,
    })


# ═══════════════════════════════════════════════════════════════
# EDIT STORE
# ═══════════════════════════════════════════════════════════════

@platform_permission_required('tenants.change_tenant')
def edit_store(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    if request.method == 'POST':
        name    = request.POST.get('name', '').strip()
        slug    = request.POST.get('slug', '').strip()
        address = request.POST.get('address', '').strip()
        phone   = request.POST.get('phone', '').strip()
        tin     = request.POST.get('tin', '').strip()
        owner   = request.POST.get('owner', '').strip()

        errors = {}
        if not name:
            errors['name'] = 'Name is required.'
        if slug and Tenant.objects.filter(slug=slug).exclude(pk=tenant.pk).exists():
            errors['slug'] = 'Slug already exists.'

        if errors:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': errors})
            for field, msg in errors.items():
                messages.error(request, msg)
            return redirect('platform_admin:store_detail', tenant_id=tenant_id)

        tenant.name    = name
        tenant.slug    = slug or tenant.slug
        tenant.address = address
        tenant.phone   = phone
        tenant.tin     = tin
        tenant.owner   = owner
        tenant.save()

        messages.success(request, 'Store updated.')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
    return redirect('platform_admin:store_detail', tenant_id=tenant_id)


# ═══════════════════════════════════════════════════════════════
# TOGGLE STORE
# ═══════════════════════════════════════════════════════════════

@platform_permission_required('tenants.change_tenant')
def toggle_store(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    if request.method == 'POST':
        tenant.is_active = not tenant.is_active
        tenant.save()
        status = 'activated' if tenant.is_active else 'deactivated'
        messages.success(request, f'Store "{tenant.name}" {status}.')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'is_active': tenant.is_active})
    return redirect('platform_admin:store_detail', tenant_id=tenant_id)


# ═══════════════════════════════════════════════════════════════
# DELETE STORE
# ═══════════════════════════════════════════════════════════════

@platform_permission_required('tenants.delete_tenant')
def delete_store(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    if request.method == 'POST':
        name = tenant.name
        with transaction.atomic():
            # Collect the User PKs before deleting profiles so we can
            # remove the Django User rows too — otherwise they become
            # orphaned accounts with no tenant affiliation.
            user_pks = list(
                UserProfile.all_objects
                .filter(tenant_id=tenant.id)
                .values_list('user_id', flat=True)
            )
            UserProfile.all_objects.filter(tenant_id=tenant.id).delete()
            User.objects.filter(pk__in=user_pks).delete()
            Sale.all_objects.filter(tenant_id=tenant.id).delete()
            Product.all_objects.filter(tenant_id=tenant.id).delete()
            tenant.delete()
        messages.success(request, f'Store "{name}" and all its data deleted.')
        return redirect('platform_admin:dashboard')
    return render(request, 'platform_admin/delete_confirm.html', {'tenant': tenant})


# ═══════════════════════════════════════════════════════════════
# ADD USER TO STORE
# ═══════════════════════════════════════════════════════════════

@platform_permission_required('accounts.add_userprofile')
def add_store_user(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email    = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        is_staff = request.POST.get('is_staff') == 'on'

        errors = {}
        if not username:
            errors['username'] = 'Required.'
        elif User.objects.filter(username=username).exists():
            errors['username'] = 'Username already taken.'
        if not password:
            errors['password'] = 'Required.'
        else:
            try:
                validate_password(password)
            except ValidationError as e:
                errors['password'] = ' '.join(e.messages)

        if errors:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': errors})
            messages.error(request, 'Please fix the errors.')
            return redirect('platform_admin:store_detail', tenant_id=tenant_id)

        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                is_staff=is_staff,
            )
            profile = UserProfile.objects.create(
                user=user,
                tenant_id=tenant.id,
                **_permissions_from_user(user),
            )

        messages.success(request, f'User "{username}" added to {tenant.name}.')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'user': _store_user_payload(user, profile),
            })
    return redirect('platform_admin:store_detail', tenant_id=tenant_id)


# ═══════════════════════════════════════════════════════════════
# REMOVE USER FROM STORE
# ═══════════════════════════════════════════════════════════════

@platform_permission_required('accounts.delete_userprofile')
def remove_store_user(request, tenant_id, user_id):
    tenant  = get_object_or_404(Tenant, id=tenant_id)
    user    = get_object_or_404(User, pk=user_id)
    profile = get_object_or_404(UserProfile.all_objects, user=user, tenant_id=tenant.id)

    # Guard: platform admins cannot remove themselves — mirrors user_delete in views.py
    if user == request.user:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'errors': {'__all__': ['You cannot remove your own account.']}})
        messages.error(request, 'You cannot remove your own account.')
        return redirect('platform_admin:store_detail', tenant_id=tenant_id)

    if request.method == 'POST':
        username = user.username
        with transaction.atomic():
            profile.delete()
            user.delete()
        messages.success(request, f'User "{username}" removed.')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'username': username})
    return redirect('platform_admin:store_detail', tenant_id=tenant_id)


# ═══════════════════════════════════════════════════════════════
# LOGIN / LOGOUT
# ═══════════════════════════════════════════════════════════════

def platform_login(request):
    # ✅ Also check app_type so an admin session isn't mistaken for already-authed
    if (request.user.is_authenticated
            and request.user.is_superuser
            and not request.session.get('tenant_id')
            and request.session.get('app_type') == 'admin'):   # ← add this
        return redirect('platform_admin:dashboard')

    form = AuthenticationForm(data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        if not user.is_superuser:
            form.add_error(None, 'This account does not have platform admin access.')
            return render(request, 'platform_admin/login.html', {'form': form})

        login(request, user)
        request.session.pop('tenant_id', None)
        request.session['app_type'] = 'admin'   # ← stamp it
        return redirect('platform_admin:dashboard')

    return render(request, 'platform_admin/login.html', {'form': form})


def platform_logout(request):
    logout(request)
    # logout() already flushes the session, but be explicit
    request.session.flush()
    return redirect('platform_admin:login')


# ─── Private helpers ─────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
# EDIT STORE USER
# ═══════════════════════════════════════════════════════════════

@platform_permission_required('accounts.change_userprofile')
def edit_store_user(request, tenant_id, user_id):
    tenant  = get_object_or_404(Tenant, id=tenant_id)
    user    = get_object_or_404(User, pk=user_id)
    profile = get_object_or_404(UserProfile.all_objects, user=user, tenant_id=tenant.id)

    if request.method == 'POST':
        username   = request.POST.get('username', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        email      = request.POST.get('email', '').strip()
        role       = request.POST.get('role', 'cashier')
        is_active  = request.POST.get('is_active') in ('1', 'true', 'on')

        errors = {}
        if not username:
            errors['username'] = 'Required.'
        elif User.objects.filter(username=username).exclude(pk=user.pk).exists():
            errors['username'] = 'Username already taken.'

        if errors:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': errors})
            messages.error(request, 'Please fix the errors.')
            return redirect('platform_admin:store_detail', tenant_id=tenant_id)

        # Map role select back to Django flags — mirrors views.py UserEditForm logic
        is_staff_flag     = role in ('admin', 'manager')
        is_superuser_flag = role == 'admin'

        # Read granular permissions from the POST
        def _bool(key):
            return request.POST.get(key) in ('1', 'true', 'on')

        perms = {
            'can_access_products'       : _bool('can_access_products'),
            'can_access_categories'     : _bool('can_access_categories'),
            'can_access_reports'        : _bool('can_access_reports'),
            'can_access_user_management': _bool('can_access_user_management'),
            'can_access_pending_sales'  : _bool('can_access_pending_sales'),
            'can_access_shift_report'   : _bool('can_access_shift_report'),
        }

        with transaction.atomic():
            user.username    = username
            user.first_name  = first_name
            user.last_name   = last_name
            user.email       = email
            user.is_staff    = is_staff_flag
            user.is_superuser= is_superuser_flag
            user.is_active   = is_active
            user.save()

            for attr, val in perms.items():
                setattr(profile, attr, val)
            profile.save()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'user': _store_user_payload(user, profile),
            })
        messages.success(request, f'User "{user.username}" updated.')
    return redirect('platform_admin:store_detail', tenant_id=tenant_id)


# ═══════════════════════════════════════════════════════════════
# RESET STORE USER PASSWORD
# ═══════════════════════════════════════════════════════════════

@platform_permission_required('accounts.change_userprofile')
def reset_store_user_password(request, tenant_id, user_id):
    from django.contrib.auth.forms import SetPasswordForm

    tenant = get_object_or_404(Tenant, id=tenant_id)
    user   = get_object_or_404(User, pk=user_id)
    # Verify the user actually belongs to this tenant before allowing a reset
    get_object_or_404(UserProfile.all_objects, user=user, tenant_id=tenant.id)

    if request.method == 'POST':
        form = SetPasswordForm(user=user, data=request.POST)
        if form.is_valid():
            form.save()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            messages.success(request, f'Password for "{user.username}" has been reset.')
            return redirect('platform_admin:store_detail', tenant_id=tenant_id)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'errors': form.errors.get_json_data()})
        messages.error(request, 'Failed to reset password.')
    return redirect('platform_admin:store_detail', tenant_id=tenant_id)


# ─── Private helpers ─────────────────────────────────────────
def _store_user_payload(user, profile):
    """
    Reusable dict for JSON responses in platform admin views.
    Mirrors _user_payload() in views.py — keep both in sync.
    Includes URL fields so JS can wire data attributes on freshly appended rows.
    """
    from django.urls import reverse
    tenant_id = profile.tenant_id
    return {
        'pk'                        : user.pk,
        'edit_url'                  : reverse('platform_admin:edit_store_user',          args=[tenant_id, user.pk]),
        'pw_url'                    : reverse('platform_admin:reset_store_user_password', args=[tenant_id, user.pk]),
        'remove_url'                : reverse('platform_admin:remove_store_user',         args=[tenant_id, user.pk]),
        'username'                  : user.username,
        'full_name'                 : user.get_full_name() or '—',
        'first_name'                : user.first_name,
        'last_name'                 : user.last_name,
        'email'                     : user.email or '—',
        'is_superuser'              : user.is_superuser,
        'is_staff'                  : user.is_staff,
        'is_active'                 : user.is_active,
        'can_access_products'       : profile.can_access_products,
        'can_access_categories'     : profile.can_access_categories,
        'can_access_reports'        : profile.can_access_reports,
        'can_access_user_management': profile.can_access_user_management,
        'can_access_pending_sales'  : profile.can_access_pending_sales,
        'can_access_shift_report'   : profile.can_access_shift_report,
    }
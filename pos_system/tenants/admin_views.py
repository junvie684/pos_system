from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from accounts.throttle import ThrottledAuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
import datetime
import logging

from django.db import DatabaseError, transaction
from django.db.models import Count, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import dateformat, timezone
from django.utils.text import slugify
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

from .decorators import is_platform_admin, platform_admin_required, platform_permission_required
from . import store_users
from .models import (
    ARCHIVE_EVERY_MAX_DAYS, ARCHIVE_EVERY_MIN_DAYS, RETENTION_MAX_DAYS, RETENTION_MIN_DAYS, Tenant,
)
from archive.services import archive_store, retention_status

logger = logging.getLogger(__name__)
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
    """Every store with its head counts and last sale, in one query."""
    def per_store(model, **filters):
        rows = (model.all_objects.filter(tenant_id=OuterRef('id'), **filters)
                .order_by().values('tenant_id'))
        return Subquery(rows.annotate(n=Count('pk')).values('n'), output_field=IntegerField())

    last_sale = (Sale.all_objects.filter(tenant_id=OuterRef('id'), status__in=['completed', 'refunded'])
                 .order_by('-created_at').values('created_at')[:1])
    tenants = list(
        Tenant.objects.order_by('name').annotate(
            user_count=Coalesce(per_store(UserProfile), 0),
            sale_count=Coalesce(per_store(Sale, status__in=['completed', 'refunded']), 0),
            product_count=Coalesce(per_store(Product), 0),
            last_sale_at=Subquery(last_sale),
        )
    )
    active = sum(1 for t in tenants if t.is_active)
    return render(request, 'platform_admin/dashboard.html', {
        'stores'         : tenants,
        'total_stores'   : len(tenants),
        'active_stores'  : active,
        'inactive_stores': len(tenants) - active,
    })


def _unique_slug(name):
    """A slug from the store name, suffixed -2, -3... until unused."""
    base = slugify(name)[:45] or 'store'
    slug, n = base, 2
    while Tenant.objects.filter(slug=slug).exists():
        slug, n = f'{base}-{n}', n + 1
    return slug


# ═══════════════════════════════════════════════════════════════
# CREATE STORE
# ═══════════════════════════════════════════════════════════════

@platform_permission_required('tenants.add_tenant')
def create_store(request):
    if request.method == 'POST':
        name           = request.POST.get('name', '').strip()
        slug           = slugify(request.POST.get('slug', '').strip())
        address        = request.POST.get('address', '').strip()
        phone          = request.POST.get('phone', '').strip()
        tin            = request.POST.get('tin', '').strip()
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
                slug=slug or _unique_slug(name),
                owner=owner_email,
                address=address,
                phone=phone,
                tin=tin,
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

            UserProfile.all_objects.create(
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
    # Platform sessions have no store in context, so the scoped manager returns
    # nothing; filter explicitly by the store being viewed.
    urls = _platform_user_urls(tenant.id)
    profiles = list(store_users.store_profiles(tenant))
    for p in profiles:
        p.urls = urls(p.user)

    paid = Sale.all_objects.filter(tenant_id=tenant.id, status__in=['completed', 'refunded'])
    last_sale = paid.order_by('-created_at').values_list('created_at', flat=True).first()
    return render(request, 'platform_admin/store_detail.html', {
        'tenant'       : tenant,
        'profiles'     : profiles,
        'add_user_url' : reverse('platform_admin:add_store_user', args=[tenant.id]),
        'product_count': Product.all_objects.filter(tenant_id=tenant.id).count(),
        'sale_count'   : paid.count(),
        'last_sale_at' : last_sale,
        'retention'    : retention_status(tenant),
        'retention_min': RETENTION_MIN_DAYS,
        'retention_max': RETENTION_MAX_DAYS,
        'archive_every_min': ARCHIVE_EVERY_MIN_DAYS,
        'archive_every_max': ARCHIVE_EVERY_MAX_DAYS,
        'next_archive_run': _next_run_label(tenant),
        'archive_hours': [(h, _hour_label(h)) for h in range(24)],
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
# DATA RETENTION
# ═══════════════════════════════════════════════════════════════

@platform_permission_required('tenants.change_tenant')
@require_POST
def update_retention(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    try:
        days = int(request.POST.get('retention_days', ''))
    except ValueError:
        days = None
    if days is None or not RETENTION_MIN_DAYS <= days <= RETENTION_MAX_DAYS:
        return JsonResponse({'success': False, 'errors': {
            'retention_days': f'Enter a number of days from {RETENTION_MIN_DAYS} to {RETENTION_MAX_DAYS}.'}})
    try:
        every = int(request.POST.get('archive_every_days', tenant.archive_every_days))
    except ValueError:
        every = None
    if every is None or not ARCHIVE_EVERY_MIN_DAYS <= every <= ARCHIVE_EVERY_MAX_DAYS:
        return JsonResponse({'success': False, 'errors': {
            'archive_every_days': f'Run automatic archiving every {ARCHIVE_EVERY_MIN_DAYS} to '
                                  f'{ARCHIVE_EVERY_MAX_DAYS} days.'}})
    try:
        hour = int(request.POST.get('archive_hour', tenant.archive_hour))
    except ValueError:
        hour = None
    if hour is None or not 0 <= hour <= 23:
        return JsonResponse({'success': False, 'errors': {'archive_hour': 'Choose an hour of the day.'}})
    tenant.retention_days = days
    tenant.archive_hour = hour
    tenant.archive_every_days = every
    tenant.auto_archive = request.POST.get('auto_archive') in ('1', 'true', 'on')
    tenant.save(update_fields=['retention_days', 'archive_hour', 'archive_every_days', 'auto_archive'])
    status = retention_status(tenant)
    return JsonResponse({
        'success': True,
        'retention_days': tenant.retention_days,
        'auto_archive': tenant.auto_archive,
        'archive_every_days': tenant.archive_every_days,
        'next_run': _next_run_label(tenant),
        'waiting': status['waiting'],
        'cutoff': dateformat.format(timezone.localtime(status['cutoff']), 'M j, Y'),
    })


def _hour_label(hour):
    return dateformat.format(datetime.time(hour), 'g:i A')


def _next_run_label(tenant):
    """When the hourly archive job will next archive this store, in words."""
    if not tenant.auto_archive:
        return 'Off'
    run = timezone.localtime(tenant.next_archive_run())
    today = timezone.localdate()
    day = ('Today' if run.date() == today else 'Tomorrow' if run.date() == today + datetime.timedelta(days=1)
           else dateformat.format(run, 'M j, Y'))
    return f'{day} at {_hour_label(run.hour)}'


@platform_permission_required('tenants.change_tenant')
@require_POST
def archive_now(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    try:
        moved = archive_store(tenant)
    except DatabaseError:
        logger.exception('Archive run failed for store %s', tenant.slug)
        messages.error(request, "Couldn't archive: the archive database isn't reachable. Nothing was moved.")
    else:
        messages.success(request, f'Moved {moved} sale{"s" if moved != 1 else ""} to the archive.'
                         if moved else 'Nothing to archive: no paid sales are past the retention period.')
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
@require_POST
def add_store_user(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    ok, result = store_users.add_user(tenant, request.POST)
    if not ok:
        return JsonResponse({'success': False, 'errors': result})
    return JsonResponse({'success': True, 'user': _store_user_payload(*result)})


# ═══════════════════════════════════════════════════════════════
# REMOVE USER FROM STORE
# ═══════════════════════════════════════════════════════════════

@platform_permission_required('accounts.delete_userprofile')
@require_POST
def remove_store_user(request, tenant_id, user_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    member = store_users.get_store_member(tenant, user_id) or _not_found()
    ok, result = store_users.remove_user(*member, acting_user=request.user)
    if not ok:
        return JsonResponse({'success': False, 'errors': result})
    return JsonResponse({'success': True, 'username': result})


# ═══════════════════════════════════════════════════════════════
# LOGIN / LOGOUT
# ═══════════════════════════════════════════════════════════════

def platform_login(request):
    # ✅ Also check app_type so an admin session isn't mistaken for already-authed
    if (is_platform_admin(request.user)
            and not request.session.get('tenant_id')
            and request.session.get('app_type') == 'admin'):
        return redirect('platform_admin:dashboard')

    form = ThrottledAuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        # Store admins are superusers too; only store-less superusers may enter.
        if not is_platform_admin(user):
            form.add_error(None, 'This account does not have platform admin access.')
            return render(request, 'platform_admin/login.html', {'form': form})

        login(request, user)
        request.session.pop('tenant_id', None)
        request.session['app_type'] = 'admin'   # ← stamp it
        return redirect('platform_admin:dashboard')

    return render(request, 'platform_admin/login.html', {'form': form})


def platform_logout(request):
    # POST only, like the POS sign-out; a plain visit goes back to the console.
    if request.method != 'POST':
        return redirect('platform_admin:dashboard')
    logout(request)
    # logout() already flushes the session, but be explicit
    request.session.flush()
    return redirect('platform_admin:login')


# ─── Private helpers ─────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
# EDIT STORE USER
# ═══════════════════════════════════════════════════════════════

@platform_permission_required('accounts.change_userprofile')
@require_POST
def edit_store_user(request, tenant_id, user_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    user, profile = store_users.get_store_member(tenant, user_id) or _not_found()
    ok, result = store_users.edit_user(tenant, user, profile, request.POST, request.user)
    if not ok:
        return JsonResponse({'success': False, 'errors': result})
    return JsonResponse({'success': True, 'user': _store_user_payload(*result)})


# ═══════════════════════════════════════════════════════════════
# RESET STORE USER PASSWORD
# ═══════════════════════════════════════════════════════════════

@platform_permission_required('accounts.change_userprofile')
@require_POST
def reset_store_user_password(request, tenant_id, user_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    user, _ = store_users.get_store_member(tenant, user_id) or _not_found()
    ok, errors = store_users.reset_password(user, request.POST)
    return JsonResponse({'success': True} if ok else {'success': False, 'errors': errors})


# ─── Private helpers ─────────────────────────────────────────
def _not_found():
    raise Http404('No such user in this store.')


def _platform_user_urls(tenant_id):
    def urls(user):
        return {
            'edit_url'  : reverse('platform_admin:edit_store_user',           args=[tenant_id, user.pk]),
            'pw_url'    : reverse('platform_admin:reset_store_user_password', args=[tenant_id, user.pk]),
            'remove_url': reverse('platform_admin:remove_store_user',         args=[tenant_id, user.pk]),
        }
    return urls


def _store_user_payload(user, profile):
    return store_users.payload(user, profile, _platform_user_urls(profile.tenant_id))

from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from functools import wraps

from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

from .decorators import admin_required
from .models import UserProfile
from .throttle import ThrottledAuthenticationForm
from tenants import store_users
from tenants.middleware import get_current_tenant_id
from tenants.models import Tenant


# ─── Auth ────────────────────────────────────────────────────
def login_view(request):
    if request.user.is_authenticated and request.session.get('app_type') == 'pos':
        return redirect('/')

    form = ThrottledAuthenticationForm(request, data=request.POST or None)
    if form.is_valid():
        user = form.get_user()
        profile = UserProfile.all_objects.filter(user=user).exclude(tenant_id__isnull=True).first()
        tenant = Tenant.objects.filter(id=profile.tenant_id).first() if profile else None

        # Every POS session must belong to exactly one existing store; otherwise
        # tenant scoping has nothing to scope to.
        if tenant is None:
            messages.error(request, 'This account is not linked to a store. Please contact your administrator.')
            return render(request, 'accounts/login.html', {'form': form})
        if not tenant.is_active:
            messages.error(request, 'This store has been deactivated. Please contact your system provider or system administrator for assistance.')
            return render(request, 'accounts/login.html', {'form': form})

        login(request, user)
        request.session['tenant_id'] = str(tenant.id)
        request.session['app_type'] = 'pos'
        return redirect('/')

    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    # POST only (the sidebar menu posts a form), so a link on another site
    # can't sign anyone out. A plain visit just goes back to the POS.
    if request.method != 'POST':
        return redirect('/')
    request.session.pop('tenant_id', None)
    request.session.pop('app_type', None)    # ← clean up on logout too
    logout(request)
    return redirect('/accounts/login/')


# ─── User Management (store admins, own store only) ──────────
def user_admin_required(view_func):
    """A POS store admin with user-management access. The store is always the
    one in the session; nothing in the URL can point at another store."""
    @admin_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        profile = UserProfile.all_objects.filter(user=request.user).first()
        tenant = Tenant.objects.filter(id=get_current_tenant_id()).first()
        if tenant is None or profile is None or not profile.can_access_user_management:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': {'__all__': 'Access denied.'}}, status=403)
            messages.error(request, "You don't have access to user management.")
            return redirect('sales:dashboard')
        request.store = tenant
        return view_func(request, *args, **kwargs)
    return _wrapped


def _pos_user_urls(user):
    return {
        'edit_url'  : reverse('accounts:user_edit',           args=[user.pk]),
        'pw_url'    : reverse('accounts:user_reset_password', args=[user.pk]),
        'remove_url': reverse('accounts:user_remove',         args=[user.pk]),
    }


def _member_or_404(request, user_id):
    member = store_users.get_store_member(request.store, user_id)
    if member is None:
        raise Http404('No such user in this store.')
    return member


def _result(ok, data_or_errors, user_payload=True):
    if not ok:
        return JsonResponse({'success': False, 'errors': data_or_errors})
    if user_payload:
        return JsonResponse({'success': True,
                             'user': store_users.payload(*data_or_errors, _pos_user_urls)})
    return JsonResponse({'success': True})


@user_admin_required
def user_list(request):
    profiles = list(store_users.store_profiles(request.store))
    for p in profiles:
        p.urls = _pos_user_urls(p.user)
    return render(request, 'accounts/user_list.html', {
        'tenant'      : request.store,
        'profiles'    : profiles,
        'add_user_url': reverse('accounts:user_add'),
    })


@user_admin_required
@require_POST
def user_add(request):
    return _result(*store_users.add_user(request.store, request.POST))


@user_admin_required
@require_POST
def user_edit(request, user_id):
    user, profile = _member_or_404(request, user_id)
    return _result(*store_users.edit_user(request.store, user, profile, request.POST, request.user))


@user_admin_required
@require_POST
def user_reset_password(request, user_id):
    user, _ = _member_or_404(request, user_id)
    return _result(*store_users.reset_password(user, request.POST), user_payload=False)


@user_admin_required
@require_POST
def user_remove(request, user_id):
    ok, result = store_users.remove_user(*_member_or_404(request, user_id), acting_user=request.user)
    if not ok:
        return JsonResponse({'success': False, 'errors': result})
    return JsonResponse({'success': True, 'username': result})

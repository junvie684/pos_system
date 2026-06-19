from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse

from .decorators import admin_required
from .models import UserProfile
from tenants.middleware import get_current_tenant_id
from tenants.models import Tenant


# ─── Auth ────────────────────────────────────────────────────
def login_view(request):
    if request.user.is_authenticated and request.session.get('app_type') == 'pos':
        return redirect('/')

    form = AuthenticationForm(data=request.POST or None)
    if form.is_valid():
        user = form.get_user()
        try:
            profile = UserProfile.all_objects.get(user=user)
            if profile.tenant_id:
                try:
                    tenant = Tenant.objects.get(id=profile.tenant_id)
                    if not tenant.is_active:
                        messages.error(request, 'This store has been deactivated. Please contact your administrator.')
                        return render(request, 'accounts/login.html', {'form': form})
                except Tenant.DoesNotExist:
                    pass

                login(request, user)
                request.session['tenant_id'] = str(profile.tenant_id)
        except UserProfile.DoesNotExist:
            login(request, user)

        request.session['app_type'] = 'pos'
        return redirect('/')

    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    request.session.pop('tenant_id', None)
    request.session.pop('app_type', None)    # ← clean up on logout too
    logout(request)
    return redirect('/accounts/login/')


# ─── User Management — Redirect to Admin Platform ────────────
@admin_required
def user_list(request):
    """Redirect POS users to the admin platform for user management."""
    tenant_id = get_current_tenant_id()
    if tenant_id:
        return redirect('platform_admin:store_detail', tenant_id=tenant_id)
    # Fallback if no tenant (shouldn't happen for POS users)
    messages.error(request, 'Unable to determine store. Please contact support.')
    return redirect('sales:dashboard')
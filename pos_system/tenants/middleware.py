import threading
import jwt
from django.conf import settings
from django.http import JsonResponse

from tenants.models import Tenant

_thread_locals = threading.local()


def get_current_tenant_id():
    return getattr(_thread_locals, 'tenant_id', None)


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_locals.tenant_id = None

        tenant_id = request.session.get('tenant_id')

        if not tenant_id:
            token = request.META.get('HTTP_AUTHORIZATION', '').replace('Bearer ', '')
            if token:
                try:
                    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
                    tenant_id = payload.get('tenant_id')
                except jwt.ExpiredSignatureError:
                    return JsonResponse({'error': 'Token expired'}, status=401)
                except jwt.InvalidTokenError:
                    return JsonResponse({'error': 'Invalid token'}, status=401)

        # ✅ Kick out already-logged-in users if tenant was deactivated
        if tenant_id and request.user.is_authenticated:
            try:
                tenant = Tenant.objects.get(id=tenant_id)
                if not tenant.is_active:
                    from django.contrib.auth import logout
                    logout(request)
                    from django.shortcuts import redirect
                    return redirect('/accounts/login/?deactivated=1')
            except Tenant.DoesNotExist:
                pass

        _thread_locals.tenant_id = tenant_id
        response = self.get_response(request)
        return response
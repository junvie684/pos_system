"""
One session per app on the same host.

The POS and the platform console are served from one domain. With a single
session cookie, signing in to one replaces the other's user (Django's login()
flushes a session that belongs to a different user), so an operator could not
be signed in to both at once. This middleware keeps a separate cookie for the
platform console, scoped to its URL prefix, so each app has its own session,
its own signed-in user and (with CSRF_USE_SESSIONS) its own CSRF secret.
"""
import time

from django.conf import settings
from django.contrib.sessions.exceptions import SessionInterrupted
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.sessions.backends.base import UpdateError
from django.utils.cache import patch_vary_headers
from django.utils.http import http_date

PLATFORM_PREFIX = '/platform/'
PLATFORM_SESSION_COOKIE_NAME = 'platform_session'


def session_cookie_for(path):
    """(cookie name, cookie path) for the app that serves this URL path."""
    if path.startswith(PLATFORM_PREFIX):
        return PLATFORM_SESSION_COOKIE_NAME, PLATFORM_PREFIX
    return settings.SESSION_COOKIE_NAME, settings.SESSION_COOKIE_PATH


class PerAppSessionMiddleware(SessionMiddleware):
    """Django's SessionMiddleware with the cookie name and path chosen per app."""

    def process_request(self, request):
        name, _ = session_cookie_for(request.path_info)
        request.session = self.SessionStore(request.COOKIES.get(name))

    def process_response(self, request, response):
        # Mirrors django.contrib.sessions.middleware.SessionMiddleware (6.0)
        # except for the cookie name and path.
        try:
            accessed = request.session.accessed
            modified = request.session.modified
            empty = request.session.is_empty()
        except AttributeError:
            return response

        name, path = session_cookie_for(request.path_info)
        if name in request.COOKIES and empty:
            response.delete_cookie(
                name, path=path,
                domain=settings.SESSION_COOKIE_DOMAIN,
                samesite=settings.SESSION_COOKIE_SAMESITE,
            )
            patch_vary_headers(response, ('Cookie',))
            return response

        if accessed:
            patch_vary_headers(response, ('Cookie',))
        if (modified or settings.SESSION_SAVE_EVERY_REQUEST) and not empty:
            if request.session.get_expire_at_browser_close():
                max_age = expires = None
            else:
                max_age = request.session.get_expiry_age()
                expires = http_date(time.time() + max_age)
            if response.status_code < 500:
                try:
                    request.session.save()
                except UpdateError:
                    raise SessionInterrupted(
                        "The request's session was deleted before the request "
                        "completed. The user may have logged out in a "
                        "concurrent request, for example."
                    )
                response.set_cookie(
                    name, request.session.session_key,
                    max_age=max_age, expires=expires,
                    domain=settings.SESSION_COOKIE_DOMAIN, path=path,
                    secure=settings.SESSION_COOKIE_SECURE or None,
                    httponly=settings.SESSION_COOKIE_HTTPONLY or None,
                    samesite=settings.SESSION_COOKIE_SAMESITE,
                )
        return response

"""
Sign-in throttling, shared by every login page (POS, platform console, Django admin).

After LOGIN_FAILURE_LIMIT failed attempts for one username, that username can't
sign in until LOGIN_LOCKOUT_SECONDS pass with no further failures. Counting is
per username (case-insensitive), not per IP: behind the hosting proxy every
client can share one address, so an IP limit would lock a whole store out.

Counts live in the cache, so production needs a cache every worker shares
(see CACHES in settings).
"""
import hashlib

from django import forms
from django.conf import settings
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.cache import cache
from django.dispatch import receiver

LOCKED_MESSAGE = 'Too many failed sign-in attempts. Wait 15 minutes, then try again.'


def _limit():
    return getattr(settings, 'LOGIN_FAILURE_LIMIT', 5)


def _window():
    return getattr(settings, 'LOGIN_LOCKOUT_SECONDS', 15 * 60)


def _key(username):
    digest = hashlib.sha256((username or '').strip().lower().encode()).hexdigest()
    return f'login-failures:{digest}'


def is_locked(username):
    return bool(username) and cache.get(_key(username), 0) >= _limit()


def record_failure(username):
    if username:
        key = _key(username)
        cache.set(key, cache.get(key, 0) + 1, _window())


def reset(username):
    cache.delete(_key(username))


@receiver(user_login_failed)
def _count_failure(sender, credentials, request=None, **kwargs):
    record_failure(credentials.get('username', ''))


@receiver(user_logged_in)
def _clear_failures(sender, request, user, **kwargs):
    reset(user.get_username())


class ThrottledLoginMixin:
    """Refuse a locked username before its password is even checked."""

    def clean(self):
        if is_locked(self.data.get('username', '')):
            raise forms.ValidationError(LOCKED_MESSAGE, code='locked')
        return super().clean()


class ThrottledAuthenticationForm(ThrottledLoginMixin, AuthenticationForm):
    pass


class ThrottledAdminAuthenticationForm(ThrottledLoginMixin, AdminAuthenticationForm):
    pass

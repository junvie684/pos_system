"""
Managing one store's users: shared by the platform console (any store, chosen
by URL) and the POS's own User management page (only the signed-in store).

Each function takes the store and the acting user and returns either
(True, data) or (False, errors), where errors maps a field (or '__all__') to a
message. The views turn that into JSON. Callers must already have checked who
may manage users; these functions only guarantee the target user belongs to
the given store.
"""
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.models import UserProfile

ROLES = ('cashier', 'manager', 'admin')
PERMISSION_FIELDS = (
    'can_access_dashboard', 'can_access_products', 'can_access_categories', 'can_access_reports',
    'can_access_user_management', 'can_access_pending_sales', 'can_access_shift_report',
)


def _flag(data, key):
    return data.get(key) in ('1', 'true', 'on')


def _role_flags(role):
    """(is_staff, is_superuser) for a role name. Store admins are superusers."""
    return role in ('admin', 'manager'), role == 'admin'


def role_of(user):
    return 'admin' if user.is_superuser else 'manager' if user.is_staff else 'cashier'


def store_profiles(tenant):
    return (UserProfile.all_objects.filter(tenant_id=tenant.id)
            .select_related('user').order_by('user__username'))


def get_store_member(tenant, user_id):
    """The (user, profile) pair if this user belongs to the store, else None."""
    profile = (UserProfile.all_objects.select_related('user')
               .filter(tenant_id=tenant.id, user_id=user_id).first())
    return (profile.user, profile) if profile else None


def payload(user, profile, urls):
    """JSON for one row of the users table. `urls(user)` gives its action URLs."""
    data = {
        'pk': user.pk,
        'username': user.username,
        'full_name': user.get_full_name() or '—',
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email or '—',
        'is_superuser': user.is_superuser,
        'is_staff': user.is_staff,
        'is_active': user.is_active,
        **{field: getattr(profile, field) for field in PERMISSION_FIELDS},
    }
    data.update(urls(user))
    return data


def add_user(tenant, data):
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    password2 = data.get('password2', password)
    role = data.get('role', 'cashier')

    errors = {}
    if not username:
        errors['username'] = 'Enter a username.'
    elif User.objects.filter(username__iexact=username).exists():
        errors['username'] = 'That username is already taken.'
    if role not in ROLES:
        errors['role'] = 'Choose a role.'
    if not password:
        errors['password'] = 'Enter a password.'
    elif password != password2:
        errors['password2'] = "The two passwords don't match."
    else:
        try:
            validate_password(password)
        except ValidationError as exc:
            errors['password'] = ' '.join(exc.messages)
    if errors:
        return False, errors

    is_staff, is_superuser = _role_flags(role)
    with transaction.atomic():
        user = User.objects.create_user(
            username=username, email=email, password=password,
            first_name=data.get('first_name', '').strip()[:150],
            last_name=data.get('last_name', '').strip()[:150],
            is_staff=is_staff, is_superuser=is_superuser,
            is_active=data.get('is_active', '1') in ('1', 'true', 'on'),
        )
        # A post_save signal may already have made a store-less profile.
        profile, _ = UserProfile.all_objects.update_or_create(
            user=user,
            defaults={'tenant_id': tenant.id,
                      **{field: _flag(data, field) for field in PERMISSION_FIELDS}},
        )
    return True, (user, profile)


def edit_user(tenant, user, profile, data, acting_user):
    username = data.get('username', '').strip()
    role = data.get('role', role_of(user))
    is_active = _flag(data, 'is_active')
    perms = {field: _flag(data, field) for field in PERMISSION_FIELDS}

    errors = {}
    if not username:
        errors['username'] = 'Enter a username.'
    elif User.objects.filter(username__iexact=username).exclude(pk=user.pk).exists():
        errors['username'] = 'That username is already taken.'
    if role not in ROLES:
        errors['role'] = 'Choose a role.'
    # Nobody may lock themselves out of the screen they are using.
    if user == acting_user:
        if role != role_of(user):
            errors['role'] = "You can't change your own role."
        if not is_active:
            errors['is_active'] = "You can't deactivate your own account."
        if profile.can_access_user_management and not perms['can_access_user_management']:
            errors['can_access_user_management'] = "You can't remove your own user management access."
    if errors:
        return False, errors

    is_staff, is_superuser = _role_flags(role)
    with transaction.atomic():
        user.username = username
        user.first_name = data.get('first_name', '').strip()[:150]
        user.last_name = data.get('last_name', '').strip()[:150]
        user.email = data.get('email', '').strip()
        user.is_staff, user.is_superuser, user.is_active = is_staff, is_superuser, is_active
        user.save()
        for field, value in perms.items():
            setattr(profile, field, value)
        profile.save()
    return True, (user, profile)


def reset_password(user, data):
    form = SetPasswordForm(user=user, data=data)
    if not form.is_valid():
        return False, {field: [e['message'] for e in errs]
                       for field, errs in form.errors.get_json_data().items()}
    form.save()
    return True, None


def remove_user(user, profile, acting_user):
    if user == acting_user:
        return False, {'__all__': "You can't remove your own account."}
    username = user.username
    with transaction.atomic():
        profile.delete()
        user.delete()
    return True, username

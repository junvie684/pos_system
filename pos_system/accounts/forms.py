from django import forms
from django.contrib.auth.models import User
from .models import UserProfile
from tenants.middleware import get_current_tenant_id


class UserCreateForm(forms.ModelForm):
    password1 = forms.CharField(widget=forms.PasswordInput)
    password2 = forms.CharField(widget=forms.PasswordInput)

    # ... keep your permission fields ...

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('password1') != cleaned.get('password2'):
            raise forms.ValidationError("Passwords don't match.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])

        # Role assignment
        if self.cleaned_data.get('can_access_user_management'):
            user.is_superuser = True
            user.is_staff = True
        elif self.cleaned_data.get('can_access_products') or self.cleaned_data.get('can_access_reports'):
            user.is_staff = True

        if commit:
            user.save()
            # Use all_objects to bypass TenantModel's automatic tenant filtering
            from tenants.middleware import get_current_tenant_id
            profile, created = UserProfile.all_objects.get_or_create(
                user=user,
                defaults={
                    'tenant_id': get_current_tenant_id(),
                    'can_access_products': self.cleaned_data.get('can_access_products', False),
                    'can_access_categories': self.cleaned_data.get('can_access_categories', False),
                    'can_access_reports': self.cleaned_data.get('can_access_reports', False),
                    'can_access_user_management': self.cleaned_data.get('can_access_user_management', False),
                    'can_access_pending_sales': self.cleaned_data.get('can_access_pending_sales', False),
                    'can_access_shift_report': self.cleaned_data.get('can_access_shift_report', False),
                }
            )
            if not created:
                profile.tenant_id = get_current_tenant_id()
                profile.can_access_products = self.cleaned_data.get('can_access_products', False)
                profile.can_access_categories = self.cleaned_data.get('can_access_categories', False)
                profile.can_access_reports = self.cleaned_data.get('can_access_reports', False)
                profile.can_access_user_management = self.cleaned_data.get('can_access_user_management', False)
                profile.can_access_pending_sales = self.cleaned_data.get('can_access_pending_sales', False)
                profile.can_access_shift_report = self.cleaned_data.get('can_access_shift_report', False)
                profile.save()
        return user


class UserEditForm(forms.ModelForm):
    can_access_products = forms.BooleanField(required=False)
    can_access_categories = forms.BooleanField(required=False)
    can_access_reports = forms.BooleanField(required=False)
    can_access_user_management = forms.BooleanField(required=False)
    can_access_pending_sales = forms.BooleanField(required=False)
    can_access_shift_report = forms.BooleanField(required=False)

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and hasattr(self.instance, 'profile'):
            profile = self.instance.profile
            self.fields['can_access_products'].initial = profile.can_access_products
            self.fields['can_access_categories'].initial = profile.can_access_categories
            self.fields['can_access_reports'].initial = profile.can_access_reports
            self.fields['can_access_user_management'].initial = profile.can_access_user_management
            self.fields['can_access_pending_sales'].initial = profile.can_access_pending_sales
            self.fields['can_access_shift_report'].initial = profile.can_access_shift_report

    def save(self, commit=True):
        user = super().save(commit=False)

        has_admin = self.cleaned_data.get('can_access_user_management', False)
        has_manager = self.cleaned_data.get('can_access_products') or self.cleaned_data.get('can_access_reports')

        if has_admin:
            user.is_superuser = True
            user.is_staff = True
        elif has_manager:
            user.is_staff = True
            user.is_superuser = False
        else:
            user.is_staff = False
            user.is_superuser = False

        if commit:
            user.save()
            profile = user.profile
            profile.can_access_products = self.cleaned_data.get('can_access_products', False)
            profile.can_access_categories = self.cleaned_data.get('can_access_categories', False)
            profile.can_access_reports = self.cleaned_data.get('can_access_reports', False)
            profile.can_access_user_management = self.cleaned_data.get('can_access_user_management', False)
            profile.can_access_pending_sales = self.cleaned_data.get('can_access_pending_sales', False)
            profile.can_access_shift_report = self.cleaned_data.get('can_access_shift_report', False)
            profile.save()
        return user
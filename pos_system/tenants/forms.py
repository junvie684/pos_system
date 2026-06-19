from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from .models import Tenant


class TenantRegistrationForm(forms.Form):
    # Store info
    store_name   = forms.CharField(max_length=100)
    store_slug   = forms.SlugField(
        max_length=50,
        help_text='URL-friendly name e.g. "cebu-branch". Letters, numbers, hyphens only.'
    )
    store_address = forms.CharField(max_length=500, required=False)
    store_phone = forms.CharField(max_length=50, required=False)
    store_tin = forms.CharField(max_length=50, required=False)

    # Owner account
    username     = forms.CharField(max_length=150)
    email        = forms.EmailField()
    password     = forms.CharField(widget=forms.PasswordInput)
    password2    = forms.CharField(widget=forms.PasswordInput, label='Confirm password')

    def clean_store_slug(self):
        slug = self.cleaned_data['store_slug'].lower()
        if Tenant.objects.filter(slug=slug).exists():
            raise forms.ValidationError('A store with this slug already exists.')
        return slug

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('This username is already taken.')
        return username

    def clean_email(self):
        email = self.cleaned_data['email']
        if Tenant.objects.filter(owner=email).exists():
            raise forms.ValidationError('A store is already registered with this email.')
        return email

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password')
        p2 = cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError({'password2': 'Passwords do not match.'})
        if p1:
            validate_password(p1)
        return cleaned
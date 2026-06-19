from django import forms
from .models import Sale, SaleItem
from django.forms import inlineformset_factory

class SaleForm(forms.ModelForm):
    class Meta:
        model = Sale
        fields = ['customer', 'status', 'payment_method', 'reference_number']

SaleItemFormSet = inlineformset_factory(
    Sale, SaleItem,
    fields=['product', 'quantity', 'unit_price'],
    extra=1, can_delete=True
)
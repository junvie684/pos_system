from django import forms
from .models import Product

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'category', 'price', 'stock', 'barcode', 'image']
        widgets = {
            'barcode': forms.TextInput(attrs={'placeholder': 'e.g. 123456789'}),
        }
from django import forms
from .models import Category, Product

class ProductForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The class-level queryset is built at import time, outside any store.
        # Rebuild it per form so it is scoped to the current store.
        self.fields['category'].queryset = Category.objects.all()

    class Meta:
        model = Product
        fields = ['name', 'category', 'price', 'stock', 'barcode']
        widgets = {
            'barcode': forms.TextInput(attrs={'placeholder': 'e.g. 123456789'}),
        }
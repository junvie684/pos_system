from .base_model import TenantModel


def _all_stores_manager(model):
    return model.all_objects if issubclass(model, TenantModel) else model._default_manager


class AllStoresAdminMixin:
    """
    Django admin is platform-only (see admin_site.py) and runs with no store in
    context, where TenantManager returns nothing. Use the unscoped manager for
    the change list and for foreign-key / many-to-many dropdowns.
    """

    def get_queryset(self, request):
        qs = _all_stores_manager(self.model).all()
        ordering = self.get_ordering(request)
        return qs.order_by(*ordering) if ordering else qs

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        kwargs.setdefault('queryset', _all_stores_manager(db_field.related_model).all())
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        kwargs.setdefault('queryset', _all_stores_manager(db_field.related_model).all())
        return super().formfield_for_manytomany(db_field, request, **kwargs)

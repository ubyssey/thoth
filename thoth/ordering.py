from django.db.models import OrderBy, F
from rest_framework.filters import OrderingFilter


class NullsLastOrderingFilter(OrderingFilter):
    # https://stackoverflow.com/questions/42899552/ignore-null-values-in-descending-order-using-django-rest-framework
    
    def get_ordering(self, request, queryset, view):
        values = super().get_ordering(request, queryset, view)
        if not values:
            return values
        return (OrderBy(F(value.lstrip("-")), descending=value.startswith("-"), nulls_last=True) for value in values)
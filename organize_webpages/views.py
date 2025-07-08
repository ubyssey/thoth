from django.shortcuts import render

from rest_framework import serializers, viewsets, filters
import django_filters.rest_framework

from webpage.models import Domain
from webpage.views import DomainSerializer
from organize_webpages.models import ThothTag, ThothTaggedItem

# Create your views here.
class ThothTagChildSerializer(serializers.HyperlinkedModelSerializer):
    domains = serializers.SerializerMethodField()

    class Meta:
        model = ThothTag
        fields = ['name', 'slug', 'domains']

    def get_domains(self, instance):
        domains = Domain.objects.filter(tags=instance)
        return DomainSerializer(domains, many=True).data


# Serializers define the API representation.
class ThothTagSerializer(serializers.HyperlinkedModelSerializer):
    domains = serializers.SerializerMethodField()
    children = serializers.SerializerMethodField()

    class Meta:
        model = ThothTag
        fields = ['name', 'slug', 'is_top_level', 'domains', 'children']

    def get_domains(self, instance):
        domains = Domain.objects.filter(id__in=list(map(lambda item: item.object_id, instance.items.filter(is_direct=True))))
        return DomainSerializer(domains, many=True).data
    
    def get_children(self, instance):
        children = instance.children.all()
        return ThothTagSerializer(children, many=True).data

# ViewSets define the view behavior.
class ThothTagViewSet(viewsets.ModelViewSet):
    queryset = ThothTag.objects.all()
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ['name', 'slug', 'is_top_level']
    serializer_class = ThothTagSerializer
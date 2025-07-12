from django.shortcuts import render
from django.db.models import F

from rest_framework import serializers, viewsets, filters
import django_filters.rest_framework

from webpage.models import Domain, WebPage
from webpage.views import DomainSerializer, DomainWithWebpagesSerializer, WebPageSerializer, WebPageWithDomainSerializer
from organize_webpages.models import ThothTag, ThothTaggedItem

# Create your views here.
class ThothTagChildSerializer(serializers.HyperlinkedModelSerializer):
    domains = serializers.SerializerMethodField()

    class Meta:
        model = ThothTag
        fields = ['id', 'name', 'slug', 'domains']

    def get_domains(self, instance):
        domains = Domain.objects.filter(tags=instance)
        return DomainSerializer(domains, many=True).data


# Serializers define the API representation.
class ThothTagNestedSerializer(serializers.HyperlinkedModelSerializer):
    webpages = serializers.SerializerMethodField()
    direct_domains = serializers.SerializerMethodField()
    children = serializers.SerializerMethodField()

    class Meta:
        model = ThothTag
        fields = ['id', 'name', 'slug', 'is_top_level', 'webpages', 'direct_domains', 'children']

    def get_webpages(self, instance):
        webpages = WebPage.objects.filter(domain_id__in=list(map(lambda item: item.object_id, instance.items.all()))).order_by(F("time_updated").desc(nulls_last=True))[:100]
        return WebPageWithDomainSerializer(webpages, many=True).data

    def get_direct_domains(self, instance):
        domains = Domain.objects.filter(id__in=list(map(lambda item: item.object_id, instance.items.filter(is_direct=True)))).order_by(F("time_updated").desc(nulls_last=True))
        return DomainWithWebpagesSerializer(domains, many=True).data
    
    def get_children(self, instance):
        children = instance.children.all()
        return ThothTagSerializer(children, many=True).data

class ThothTagSerializer(serializers.HyperlinkedModelSerializer):
    direct_domains = serializers.SerializerMethodField()
    children = serializers.SerializerMethodField()

    class Meta:
        model = ThothTag
        fields = ['id', 'name', 'slug', 'is_top_level', 'direct_domains', 'children']

    def get_direct_domains(self, instance):
        domains = Domain.objects.filter(id__in=list(map(lambda item: item.object_id, instance.items.filter(is_direct=True)))).order_by(F("time_updated").desc(nulls_last=True))
        return DomainSerializer(domains, many=True).data
    
    def get_children(self, instance):
        children = instance.children.all()
        return ThothTagSerializer(children, many=True).data

# ViewSets define the view behavior.
class ThothTagViewSet(viewsets.ModelViewSet):
    queryset = ThothTag.objects.all()
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ['id', 'name', 'slug', 'is_top_level']
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ThothTagNestedSerializer
        return ThothTagSerializer
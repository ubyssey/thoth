from django.shortcuts import render
from django.db.models import F, Q, Count
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import serializers, viewsets, status, permissions, filters
import django_filters.rest_framework

import asyncio
from asgiref.sync import async_to_sync

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
class ThothTagNestedFullSerializer(serializers.HyperlinkedModelSerializer):
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
        return ThothTagNestedFullSerializer(children, many=True).data

class ThothTagNestedSerializer(serializers.HyperlinkedModelSerializer):
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
        return ThothTagNestedSerializer(children, many=True).data
    
class ThothTagSerializer(serializers.HyperlinkedModelSerializer):
    parents = serializers.PrimaryKeyRelatedField(queryset=ThothTag.objects.all(), many=True)

    class Meta:
        model = ThothTag
        fields = ['id', 'name', 'slug', 'is_top_level', 'parents']

# ViewSets define the view behavior.

class ThothTagNestedViewSet(viewsets.ModelViewSet):
    queryset = ThothTag.objects.all()
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ['id', 'name', 'slug', 'is_top_level']
    
    def get_queryset(self):
        query = Q()
        if self.request.query_params.get('is_root'):
            query = Q(query, Q(parents_count=0))
        return ThothTag.objects.alias(parents_count=Count("parents")).filter(query)

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ThothTagNestedFullSerializer
        return ThothTagNestedSerializer

class ThothTagViewSet(viewsets.ModelViewSet):
    queryset = ThothTag.objects.all()
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ['id', 'name', 'slug', 'is_top_level']
    serializer_class = ThothTagSerializer


@api_view(['PUT'])
@permission_classes((permissions.IsAuthenticated,))
def add_domain(request):
    if request.method == 'PUT':
        url = request.data.get('url')
        tag = request.data.get('tag')

        domain = None
        try:
            domain = Domain.objects.get(url=url)

        except ObjectDoesNotExist:
            if url[-1] == "/":
                url = url[:-1]

            print(url)
            async def get_real_domain(url):
                domain = await Domain.objects.acreate(url=url, is_source=True, time_discovered=timezone.now())

                webpages_to_hit = await domain.get_webpage_to_hit()
                webpages = await asyncio.gather(*webpages_to_hit)
                print(webpages)
                webpages = filter(lambda wp: wp != None, webpages)
                webpages = list(filter(lambda wp: wp.level == 0, webpages))
                print(webpages)
                if len(webpages) == 0:
                    return None
                return webpages[0].domain

            domain = async_to_sync(get_real_domain)(url)

            if domain == None:            
                return Response({'error': 'Oops'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except:
            return Response({'error': 'Oops'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        domain.tags.add(tag)

        return Response({'url': domain.url}, status=status.HTTP_200_OK)
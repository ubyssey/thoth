from django.shortcuts import render
from django.http import HttpResponse
from django.db.models import Q, F
from django.utils import timezone
from django.urls import include, path

from rest_framework import serializers, viewsets, filters

import asyncio
from asgiref.sync import async_to_sync, sync_to_async

import thoth.views as views
from webpage.models import WebPage, Domain, Referral

# Create your views here.

def index(request):
    scrape_all()
    return HttpResponse("Hello, world. You're at the polls index.")

@async_to_sync
async def scrape_all():
    tasks = []
    domain_query = Q(time_last_requested__lte=timezone.now() - timezone.timedelta(seconds=120)) | Q(time_last_requested=None)
    async for domain in Domain.objects.filter(domain_query).order_by("-is_source", "time_discovered"):
        wps = await domain.get_webpage_to_hit()
        if wps == None:
            continue
        async for wp in wps:
            tasks.append(asyncio.create_task(wp.hit()))
        if len(tasks) > 50:
            await asyncio.gather(*tasks)
            tasks = []

    await asyncio.gather(*tasks)

# Serializers define the API representation.
class WebPageSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = WebPage
        fields = ['url', 'title', 'description', 'time_updated']

# ViewSets define the view behavior.
class WebPageViewSet(viewsets.ModelViewSet):
    queryset = WebPage.objects.filter(is_redirect=False, domain__is_redirect=False)
    filter_backends = [filters.SearchFilter]
    serializer_class = WebPageSerializer

# Serializers define the API representation.
class DomainSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Domain
        fields = ['url', 'title', 'description', 'time_updated']

# ViewSets define the view behavior.
class DomainViewSet(viewsets.ModelViewSet):
    queryset = Domain.objects.filter(is_redirect=False)
    filter_backends = [filters.SearchFilter]
    serializer_class = DomainSerializer
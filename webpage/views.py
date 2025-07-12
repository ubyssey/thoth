from django.shortcuts import render
from django.http import HttpResponse
from django.db.models import Q, F
from django.utils import timezone
from django.urls import include, path

from rest_framework import serializers, viewsets, filters
import django_filters.rest_framework

import asyncio
from asgiref.sync import async_to_sync, sync_to_async

import thoth.views as views
from webpage.models import WebPage, Domain, Referral

# Create your views here.

def index(request):
    scrape_all()
    return HttpResponse("Hello, world. You're at the polls index.")

def scrape_domain(request):
    domain = request.GET.get('domain', None)
    if domain != None:
        scrape_single_domain(domain)
    return HttpResponse("Hello, world. You're at the polls index.")


@async_to_sync
async def scrape_all():
    DOMAIN_TIMEOUT = timezone.timedelta(minutes=2)
    MAX_TASKS = 500

    tasks = []
    domain_query = Q(time_last_requested__lte=timezone.now() - DOMAIN_TIMEOUT) | Q(time_last_requested=None)
    #async for domain in Domain.objects.filter(domain_query).order_by("-is_source", F("time_updated").desc(nulls_last=True), "time_discovered"):
    async for domain in Domain.objects.filter(domain_query).order_by("time_last_requested"):
        wps = await domain.get_webpage_to_hit()
        tasks = tasks + wps

        if len(tasks) > MAX_TASKS:
            await asyncio.gather(*tasks)
            tasks = []

    await asyncio.gather(*tasks)


@async_to_sync
async def scrape_single_domain(domain_url):

    tasks = []
    domain = await Domain.objects.aget(url=domain_url)

    wps = await domain.get_webpage_to_hit()
    tasks = tasks + wps

    if len(tasks) > 50:
        await asyncio.gather(*tasks)
        tasks = []

    await asyncio.gather(*tasks)


# Serializers define the API representation.
class WebPageSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = WebPage
        fields = ['url', 'title', 'description', 'image','time_updated']

# Serializers define the API representation.
class WebPageWithDomainSerializer(serializers.HyperlinkedModelSerializer):
    domain = serializers.SerializerMethodField()

    class Meta:
        model = WebPage
        fields = ['url', 'title', 'description', 'image', 'domain', 'time_updated']

    def get_domain(self, instance):
        return DomainSerializer(instance.domain).data

# ViewSets define the view behavior.
class WebPageViewSet(viewsets.ModelViewSet):
    queryset = WebPage.objects.filter(is_redirect=False, domain__is_redirect=False).order_by(F("time_updated").desc(nulls_last=True), F("time_last_requested").desc(nulls_last=True))
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['id', 'url', 'domain_id']
    search_fields = ["url", "title", "description"]
    serializer_class = WebPageWithDomainSerializer

# Serializers define the API representation.
class DomainWithWebpagesSerializer(serializers.HyperlinkedModelSerializer):
    webpages = serializers.SerializerMethodField()

    class Meta:
        model = Domain
        fields = ['id', 'url', 'title', 'description', 'image', 'time_updated', 'webpages']

    def get_webpages(self, instance):
        webpages = instance.webpages.filter(is_redirect=False).order_by(F("time_updated").desc(nulls_last=True), F("time_last_requested").desc(nulls_last=True))[:5]
        return WebPageSerializer(webpages, many=True).data

class DomainSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = Domain
        fields = ['id', 'url', 'title', 'description', 'image', 'time_updated']

# ViewSets define the view behavior.
class DomainViewSet(viewsets.ModelViewSet):
    queryset = Domain.objects.filter(is_redirect=False).order_by(F("time_updated").desc(nulls_last=True), F("time_last_requested").desc(nulls_last=True))
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ['id', 'url']
    serializer_class = DomainWithWebpagesSerializer
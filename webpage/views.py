from django.shortcuts import render
from django.http import HttpResponse
from django.db.models import Q, F, Count, Min
from django.utils import timezone
from django.urls import include, path

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import serializers, viewsets, filters

import asyncio
from asgiref.sync import async_to_sync, sync_to_async

from pgvector.django import L2Distance
from sentence_transformers import SentenceTransformer

import thoth.views as views
from webpage.models import WebPage, Domain, Referral, Embeddings
from organize_webpages.models import ThothTag

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
    filterset_fields = ['id', 'url', 'domain_id']
    search_fields = ["url", "title", "description"]
    serializer_class = WebPageWithDomainSerializer

    def get_queryset(self):
        retrieveModel = SentenceTransformer("paraphrase-MiniLM-L3-v2")

        query  = self.request.query_params.get('smart-search')
        if query != None:
            query__retrieve_embedding = retrieveModel.encode(query)
            return WebPage.objects.alias(similarity=Min(L2Distance("embeddings__embedding", query__retrieve_embedding))).filter(Q(similarity__lte=5) | Q(title__search=query)).order_by("similarity")
            
        return WebPage.objects.filter(is_redirect=False, domain__is_redirect=False).order_by(F("time_updated").desc(nulls_last=True), F("time_last_requested").desc(nulls_last=True))

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
    #filter_backends = [django_filters.rest_framework.DjangoFilterBackend, filters.SearchFilter]
    model = Domain
    filterset_fields = ['id', 'url']
    search_fields = ["url", "title", "description"]
    ordering_fields = ["time_updated", "time_last_requested", "time_discovered"]
    serializer_class = DomainWithWebpagesSerializer

    def get_queryset(self):
        filter = Q(is_redirect=False)
        exclude = None
        is_tagged = self.request.query_params.get('is_tagged')
        if is_tagged != None:
            tags = [tag.id for tag in ThothTag.objects.all()]
            if is_tagged == 'false':
                exclude = Q(tags__id__in=tags)
            else:
                filter = filter & Q(tags__id__in=tags)

        if exclude != None:
            return Domain.objects.filter(filter).exclude(exclude).order_by(F("time_updated").desc(nulls_last=True), F("time_last_requested").desc(nulls_last=True))
        return Domain.objects.filter(filter).order_by(F("time_updated").desc(nulls_last=True), F("time_last_requested").desc(nulls_last=True))

'''
import torch
from sentence_transformers import SentenceTransformer
from bs4 import BeautifulSoup
import urllib
import math
from pgvector.django import L2Distance

@api_view()
def answer(request):
    answerModel = SentenceTransformer("msmarco-distilbert-dot-v5")
    retrieveModel = SentenceTransformer("paraphrase-MiniLM-L3-v2")

    query  = request.GET.get('q', None)
    query__retrieve_embedding = retrieveModel.encode(query)
    query__answer_embedding = answerModel.encode(query)

    webpage = Embeddings.objects.order_by(L2Distance('embedding', query__retrieve_embedding))[0].webpage

    req = urllib.request.Request(webpage.url, headers = { 'User-Agent' : 'Thoth' })
    page = urllib.request.urlopen(req).read()
    soup = BeautifulSoup(page, "html.parser")
    stripped_string = [repr(string) for string in soup.stripped_strings]

    print(stripped_string)

    def rank(strings):

        passage_embedding = answerModel.encode(strings)

        top_k = max(math.ceil(len(strings) / 8), 3)

        similarity_scores = answerModel.similarity(query__answer_embedding, passage_embedding)[0]
        scores, indices = torch.topk(similarity_scores, k=top_k)

        for i in range(top_k):
            print(f'{i}. {scores[i]:.4f} {strings[indices[i]]}')

        return scores, indices

    def find_best(full_strings, string_firsts, string_lengths, best):
        strings = list(map(lambda first: " ".join(full_strings[first:first+string_lengths]), string_firsts))
        for string in strings:
            print(string)
        scores, indices = rank(strings)
        if scores[0] > best or len(strings[0]) < len(query) * 2:

            length = string_lengths + 1

            expanded_strings = []
            for i in indices:
                expanded_strings.append(string_firsts[i])
                expanded_strings.append(string_firsts[i]+1)
            expanded_strings = list(filter(lambda first: first >0 and first+length <len(full_strings), expanded_strings))

            return find_best(full_strings, expanded_strings, length, scores[0])
        else:
            return " ".join(full_strings[string_firsts[indices[0]]:string_firsts[indices[0]]+string_lengths]), scores[0]

    answer, score = find_best(stripped_string, [i for i in range(len(stripped_string))], 1, 0)
    print(f"answer ({score:.4f}): '{answer}'")

    return Response({
        "answer": answer,
        "webpage": webpage,
        "domain": webpage.domain
        })
'''
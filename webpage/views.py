from django.shortcuts import render
from django.http import HttpResponse
from django.db.models import Q, F, Count, Min
from django.utils import timezone
from django.urls import include, path

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import serializers, viewsets, filters, permissions

import asyncio
import aiohttp
from asgiref.sync import async_to_sync, sync_to_async

from pgvector.django import L2Distance

import string as py_string

import torch
from bs4 import BeautifulSoup
from pypdf import PdfReader
from io import BytesIO
import urllib
import math
from pgvector.django import L2Distance
from thoth.settings import SIMILARITY_MODEL, QUESTION_ANSWER_MODEL

import thoth.views as views
from webpage.models import WebPage, Domain, Referral, Embeddings
from organize_webpages.models import ThothTag

def is_non_whitespace(s):
    return any(char not in py_string.whitespace for char in s)

def remove_contiguous_whitespace(s):
    return " ".join(filter(is_non_whitespace, s.split()))

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
    DOMAIN_TIMEOUT = timezone.timedelta(minutes=30)
    MAX_TASKS = 1

    tasks = []
    domain_query = Q(time_last_requested__lte=timezone.now() - DOMAIN_TIMEOUT) | Q(time_last_requested=None)
    #async for domain in Domain.objects.filter(domain_query).order_by("-is_source", F("time_updated").desc(nulls_last=True), "time_discovered"):
    async for domain in Domain.objects.filter(domain_query).order_by("time_last_requested"):
        wps = await domain.get_webpage_to_hit()
        #tasks = tasks + wps

        #if len(tasks) >= MAX_TASKS:
        #    break
        #    await asyncio.gather(*tasks)
        #    tasks = []

    #if len(tasks) > 0:
    #    await asyncio.gather(*tasks)

    print(f"finished scape all")


@async_to_sync
async def scrape_single_domain(domain_url):

    tasks = []
    domain = await Domain.objects.aget(url=domain_url)

    wps = await domain.get_webpage_to_hit()
    #tasks = tasks + wps

    #if len(tasks) > 50:
    #    await asyncio.gather(*tasks)
    #    tasks = []

    #await asyncio.gather(*tasks)

# Serializers define the API representation.
class WebPageSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = WebPage
        fields = ['url', 'title', 'description', 'image','time_updated', 'time_published']

# Serializers define the API representation.
class WebPageWithDomainSerializer(serializers.HyperlinkedModelSerializer):
    domain = serializers.SerializerMethodField()

    class Meta:
        model = WebPage
        fields = ['url', 'title', 'description', 'image', 'domain', 'time_updated', 'time_published']

    def get_domain(self, instance):
        return DomainSerializer(instance.domain).data

# ViewSets define the view behavior.
class WebPageViewSet(viewsets.ModelViewSet):
    filterset_fields = ['id', 'url', 'domain_id']
    search_fields = ["url", "title", "description"]
    ordering_fields = ["time_updated", "time_last_requested", "time_discovered", 'time_published']
    serializer_class = WebPageWithDomainSerializer

    def get_queryset(self):
        
        query  = self.request.query_params.get('smart-search')
        if query != None:
            query__retrieve_embedding = SIMILARITY_MODEL.encode(query)
            return WebPage.objects.alias(similarity=Min(L2Distance("embeddings__embedding", query__retrieve_embedding))).filter(Q(similarity__lte=6) | Q(title__search=query)).order_by("similarity")
            
        return WebPage.objects.filter(is_redirect=False, domain__is_redirect=False).order_by(F("time_updated").desc(nulls_last=True), F("time_last_requested").desc(nulls_last=True))

# Serializers define the API representation.
class DomainWithWebpagesSerializer(serializers.HyperlinkedModelSerializer):
    webpages = serializers.SerializerMethodField()

    class Meta:
        model = Domain
        fields = ['id', 'url', 'title', 'description', 'image', 'time_updated', 'time_discovered', 'webpages']

    def get_webpages(self, instance):
        webpages = instance.webpages.filter(is_redirect=False).order_by(F("time_updated").desc(nulls_last=True), F("time_last_requested").desc(nulls_last=True))[:5]
        return WebPageSerializer(webpages, many=True).data

class DomainSerializer(serializers.HyperlinkedModelSerializer):

    class Meta:
        model = Domain
        fields = ['id', 'url', 'title', 'description', 'image', 'time_updated', 'time_discovered']

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

        was_requested = self.request.query_params.get('was_requested')
        if was_requested != None:
            if was_requested == 'true':
                if exclude == None:
                    exclude = Q(time_last_requested=None)
                else:
                    exclude = exclude | Q(time_last_requested=None)
            else:
                filter = filter & Q(time_last_requested=None)

        if exclude != None:
            return Domain.objects.filter(filter).exclude(exclude).order_by(F("time_updated").desc(nulls_last=True), F("time_last_requested").desc(nulls_last=True))
        return Domain.objects.filter(filter).order_by(F("time_updated").desc(nulls_last=True), F("time_last_requested").desc(nulls_last=True))


@api_view()
@permission_classes((permissions.AllowAny,))
def answer(request):

    print(f'recieve request')
    
    NUMBER_OF_ANSWERS = 3
    
    query  = request.GET.get('q', None)
    
    start = timezone.now()
    query__retrieve_embedding = SIMILARITY_MODEL.encode(query)
    print(f'encode query similarity {timezone.now() - start}')
    
    start = timezone.now()
    query__answer_embedding = QUESTION_ANSWER_MODEL.encode(query)
    print(f'encode query answer {timezone.now() - start}')

    webpage = request.GET.get('webpage', None)

    async def rank(strings):
        start = timezone.now()

        start = timezone.now()
        passage_embedding = await sync_to_async(QUESTION_ANSWER_MODEL.encode)(strings)
        print(f'encode passages {timezone.now() - start}')

        top_k = max(math.ceil(len(strings) / 8), min(3, len(strings)))

        start = timezone.now()
        similarity_scores = (await sync_to_async(QUESTION_ANSWER_MODEL.similarity)(query__answer_embedding, passage_embedding))[0]
        scores, indices = torch.topk(similarity_scores, k=top_k)
        print(f'rank passages {timezone.now() - start}')

        for i in range(top_k):
            print(f'  - {i}. {scores[i]:.4f} {strings[indices[i]]}')

        print(f'rank {timezone.now() - start}')

        return scores, indices

    async def find_best(full_strings, string_firsts, string_lengths, best):
        strings = list(map(lambda first: " ".join(full_strings[first:first+string_lengths]), string_firsts))
        if len(strings) == 0:
            return "", 0
        
        #for string in strings:
        #    print(string)
        scores, indices = await rank(strings)
        if (scores[0] > best or len(strings[0]) < len(query) * 2):

            start = timezone.now()

            length = string_lengths + 1

            expanded_strings = []
            for i in indices:
                expanded_strings.append(string_firsts[i])
                expanded_strings.append(string_firsts[i]-1)
            expanded_strings = list(filter(lambda first: first >=0 and first+length < len(full_strings), expanded_strings))

            print(f'expand {timezone.now() - start}')

            if len(expanded_strings) == 0:
                return " ".join(full_strings[string_firsts[indices[0]]:string_firsts[indices[0]]+string_lengths]), scores[0]

            return await find_best(full_strings, expanded_strings, length, scores[0])
        else:
            return " ".join(full_strings[string_firsts[indices[0]]:string_firsts[indices[0]]+string_lengths]), scores[0]

    async def retrieve_answer(url):
        
        HEADER = {'user-agent': 'The Society of Thoth'}
        stripped_string = []
        print(f'start\n  - {url}')
        start = timezone.now()
        try:
            async with aiohttp.ClientSession(headers=HEADER, max_line_size=8190 * 2, max_field_size=8190 * 2) as session:
                async with session.get(url) as r:
                    if "pdf" in r.content_type:
                        reader = PdfReader(BytesIO(await r.read()))

                        out = ""
                        for i in range(reader.get_num_pages()):
                            page = reader.pages[i]
                            text = page.extract_text()
                            out = out + text
                        
                        stripped_string = out.split("\n")

                    elif "html" in r.content_type:
                        page = await r.text()
                        soup = BeautifulSoup(page, "html.parser")
                        
                        if len(soup.find_all('article')) == 1:
                            stripped_string = soup.find('article').get_text()
                        elif len(soup.find_all("main")) == 1:
                            stripped_string = soup.find("main").get_text()
                        else:
                            for elem in soup.find_all('footer'):
                                elem.decompose()
                            for elem in soup.find_all('nav'):
                                elem.decompose()
                            for elem in soup.find_all('header'):
                                elem.decompose()
                            for elem in soup.find_all(class_='navbar'):
                                elem.decompose()
                            stripped_string = soup.get_text()

                        while '\n\n' in stripped_string:
                            stripped_string = stripped_string.replace('\n\n', '\n')
                        stripped_string = stripped_string.split('\n')

                        stripped_string = map(lambda string: map(remove_contiguous_whitespace, string.split(". ")), stripped_string)
                        stripped_string = map(lambda strings: list(filter(is_non_whitespace, strings)), stripped_string)
                        stripped_string = filter(lambda strings: len(strings) > 0, stripped_string)
                        stripped_string = [string[0]+"." for string in [strings for strings in stripped_string]]

                    else:
                        print(f'{r.content_type} {url}')
                        return url, 0

        except Exception as e: 
            print(f"error: {url}, {e}")
            return url, 0

        print(f'request {timezone.now() - start}\n  - {url}')

        return await find_best(stripped_string, [i for i in range(len(stripped_string))], 1, 0)

    async def add_answer_from_matching_page(id, answers):
        webpage = await WebPage.objects.aget(id=id)
        print(f'answering from {webpage.url}')
        answer, score = await retrieve_answer(webpage.url)
        answers.append(
            {
                "url": webpage.url,
                "title": webpage.title,
                "answer": answer,
                "score": score,
            })
        return answers

    async def answer_from_matching_pages():
        answers = []
        start = timezone.now()
        embeds = Embeddings.objects.order_by(L2Distance('embedding', query__retrieve_embedding))
        print(f'retrieve pages {timezone.now() - start}')

        start = timezone.now()
        tasks = []
        unique_pages = []
        i = 0
        gap = NUMBER_OF_ANSWERS * 2

        start = timezone.now()
        embed_count = await embeds.acount()
        print(f'count embeds {timezone.now() - start}')

        while i < embed_count:
            print(f'another loop {timezone.now() - start}')
            async for embed in embeds[i:i+gap]:
                print(f'unique webpage {embed.webpage_id} {timezone.now() - start}')
                if not embed.webpage_id in unique_pages:
                    tasks.append(asyncio.create_task(add_answer_from_matching_page(embed.webpage_id, answers)))
                    unique_pages.append(embed.webpage_id)
                    if len(unique_pages) >= NUMBER_OF_ANSWERS:
                        break

            if len(unique_pages) >= NUMBER_OF_ANSWERS:
                break

            i = i + gap

        print(f'get unique webpages {timezone.now() - start}')

        await asyncio.gather(*tasks)

        return answers

    answers = []
    if webpage == None:
        answers = async_to_sync(answer_from_matching_pages)()
    else:
        answer, score = async_to_sync(retrieve_answer)(webpage)
        answers.append(
            {
                "url": webpage,
                "title": webpage.url,
                "answer": answer.split("\n"),
                "score": score,
            })

    answers = sorted(answers, key=lambda answer: answer["score"], reverse=True) 

    return Response({
        "answers": answers,
        })
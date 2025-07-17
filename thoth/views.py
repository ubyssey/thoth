import urllib.request
from django.shortcuts import render
from django.http import HttpResponse
from django.db.models import Q
from django.utils import timezone

import asyncio
import aiohttp
from asgiref.sync import async_to_sync, sync_to_async

from io import BytesIO
import torch
from sentence_transformers import SentenceTransformer, util
from bs4 import BeautifulSoup
import urllib
import math
from pgvector.django import L2Distance
from pypdf import PdfReader

from webpage.models import Domain, WebPage, Embeddings

# Create your views here.

def index(request):
    context = {}
    context["domains"] = Domain.objects.all().order_by("-is_source", "title")
    context["webpages"] = WebPage.objects.all().order_by("-time_updated")[:100]
    return render(request, "webpage/index.html", context=context)

def domain(request, domain_id):
    domain = Domain.objects.get(id=domain_id)
    context = {}
    context["domains"] = Domain.objects.all().order_by("-is_source", "title")
    context["webpages"] = WebPage.objects.filter(domain=domain).order_by("-is_source", "level", "-time_updated")
    return render(request, "webpage/index.html", context=context)

def answer_query(request):
    answerModel = SentenceTransformer("msmarco-distilbert-dot-v5")
    retrieveModel = SentenceTransformer("paraphrase-MiniLM-L3-v2")

    query  = request.GET.get('q', None)
    query__retrieve_embedding = retrieveModel.encode(query)
    query__answer_embedding = answerModel.encode(query)

    webpage = request.GET.get('webpage', None)

    def rank(strings):

        passage_embedding = answerModel.encode(strings)

        top_k = max(math.ceil(len(strings) / 8), min(3, len(strings)))

        print(strings)
        print(len(strings))
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
        if (scores[0] > best or len(strings[0]) < len(query) * 2):

            length = string_lengths + 1

            expanded_strings = []
            for i in indices:
                expanded_strings.append(string_firsts[i])
                expanded_strings.append(string_firsts[i]-1)
            expanded_strings = list(filter(lambda first: first >=0 and first+length < len(full_strings), expanded_strings))

            if len(expanded_strings) == 0:
                return " ".join(full_strings[string_firsts[indices[0]]:string_firsts[indices[0]]+string_lengths]), scores[0]

            return find_best(full_strings, expanded_strings, length, scores[0])
        else:
            return " ".join(full_strings[string_firsts[indices[0]]:string_firsts[indices[0]]+string_lengths]), scores[0]

    async def retrieve_answer(url):
        
        HEADER = {'user-agent': 'The Society of Thoth'}
        stripped_string = []
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
                        
                        stripped_string = out.split(".")

                    elif "html" in r.content_type:
                        page = await r.text()
                        soup = BeautifulSoup(page, "html.parser")
                        
                        if len(soup.find_all('article')) == 1:
                            stripped_string = soup.find('article').get_text().split(".")
                        elif len(soup.find_all("main")) == 1:
                            stripped_string = soup.find("main").get_text().split(".")
                        else:
                            stripped_string = soup.get_text().split(".")
                    else:
                        print(f'{r.content_type} {url}')
                        return url, 0

        except Exception as e: 
            print(f"error: {url}, {e}")
            return url, 0

        print(stripped_string)

        return find_best(stripped_string, [i for i in range(len(stripped_string))], 1, 0)

    async def answer_from_matching_pages():
        answers = []
        embeds = Embeddings.objects.order_by(L2Distance('embedding', query__retrieve_embedding))[:5]
        async for embed in embeds:
            webpage = await WebPage.objects.aget(id=embed.webpage_id)
            answer, score = await retrieve_answer(webpage.url)
            answers.append(
                {
                    "url": webpage.url,
                    "title": webpage.title,
                    "answer": answer.split("\n"),
                    "score": score,
                })
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

    context = {
        "query": query,
        "answers": answers
        }
    return render(request, "webpage/answer.html", context=context)
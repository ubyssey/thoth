import urllib.request
from django.shortcuts import render
from django.http import HttpResponse
from django.db.models import Q
from django.utils import timezone

import torch
from sentence_transformers import SentenceTransformer, util
from bs4 import BeautifulSoup
import urllib
import math

from webpage.models import Domain, WebPage

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
    webpage = request.GET.get('webpage', None)
    query  = request.GET.get('q', None)

    req = urllib.request.Request(webpage, headers = { 'User-Agent' : 'Thoth' })
    page = urllib.request.urlopen(req).read()
    soup = BeautifulSoup(page, "html.parser")
    stripped_string = [repr(string) for string in soup.stripped_strings]

    print(stripped_string)

    model = SentenceTransformer("msmarco-distilbert-dot-v5")
    def rank(strings):

        query_embedding = model.encode(query)
        passage_embedding = model.encode(strings)

        top_k = max(math.ceil(len(strings) / 8), 3)

        similarity_scores = model.similarity(query_embedding, passage_embedding)[0]
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

    context = {
        "title": soup.title.string,
        "query": query,
        "answer": answer
        }
    return render(request, "webpage/answer.html", context=context)
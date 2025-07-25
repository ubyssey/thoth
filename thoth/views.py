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
from bs4 import BeautifulSoup
import urllib
import math
from pgvector.django import L2Distance
from pypdf import PdfReader

from thoth.settings import SIMILARITY_MODEL
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
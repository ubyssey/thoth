from django.shortcuts import render
from django.http import HttpResponse
from django.db.models import Q
from django.utils import timezone

from webpage.models import Domain, WebPage

# Create your views here.

def index(request):
    context = {}
    context["domains"] = Domain.objects.all().order_by("-is_source", "title")
    context["webpages"] = WebPage.objects.all().order_by("-time_discovered")[:100]
    return render(request, "webpage/index.html", context=context)

def domain(request, domain_id):
    domain = Domain.objects.get(id=domain_id)
    context = {}
    context["domains"] = Domain.objects.all().order_by("-is_source", "title")
    context["webpages"] = WebPage.objects.filter(domain=domain).order_by("-is_source", "level", "-time_discovered")
    return render(request, "webpage/index.html", context=context)


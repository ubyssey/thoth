from django.shortcuts import render
from django.http import HttpResponse
from django.db.models import Q
from django.utils import timezone

from .models import Domain
import asyncio
from asgiref.sync import async_to_sync, sync_to_async

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
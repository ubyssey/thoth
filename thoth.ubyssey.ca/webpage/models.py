from django.db import models
from django.utils import timezone
from django.db.models import Q

from urllib.parse import urlparse, urljoin
import asyncio
import aiohttp
from asgiref.sync import async_to_sync, sync_to_async

from bs4 import BeautifulSoup

# Create your models here.

class AbstractWebObject(models.Model):
    url = models.URLField(max_length=255)
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True, null=True)
    
    time_updated = models.DateTimeField(blank=True, null=True)

    time_discovered = models.DateTimeField()
    time_last_requested = models.DateTimeField(blank=True, null=True)

    is_source = models.BooleanField(default=False)

    def __str__(self):
        return self.url

    class Meta():
        abstract = True

class Domain(AbstractWebObject):
    robots_txt = models.TextField(blank=True, null=True)
    time_last_checked_robots_txt = models.DateTimeField(blank=True, null=True)

    def check_robots_txt(self):
        pass

    async def get_webpage_to_hit(self):
        print("domain: " + self.url)
        HIT_COUNT = 1
        if await WebPage.objects.filter(domain=self).aexists():
            hit_query = WebPage.objects.filter(Q(domain=self), Q(is_source=True) | Q(time_last_requested=None))
            if await hit_query.aexists():
                #return await hit_query.order_by('-is_source', 'level', 'time_last_requested', '-time_updated').afirst()
                return hit_query.order_by('level', 'time_last_requested', '-time_updated')[:HIT_COUNT]
            return None
        else:
            return await [WebPage.objects.acreate(
                url=self.url,
                title=self.title,
                description=self.description,
                time_updated=self.time_updated,
                time_discovered=self.time_discovered,
                is_source=self.is_source,

                domain=self,
                level=0
                )]
    

class WebPage(AbstractWebObject):
    domain = models.ForeignKey(Domain, on_delete=models.CASCADE)
    level = models.IntegerField(default=0)
    
    @sync_to_async
    def new_link(self, link, name):
        link_parse = urlparse(link)
        if not WebPage.objects.filter(url=link).exists():
            if 'ubc.ca' in self.url or 'ubc.ca' in link:
                level = link_parse.path.count("/")
                if level > 0:
                    if link_parse.path[-1] == "/":
                        level = level - 1

                link_domain = self.get_link_domain(link)
                WebPage.objects.create(
                    url=link,
                    title=name,
                    time_discovered = timezone.now(),
                    level = level,
                    domain=link_domain
                    )
            return True
        return False

    def get_link_domain(self, link):
        link_parse = urlparse(link)
        link_domain_str = link_parse.scheme + "://" + link_parse.hostname

        if Domain.objects.filter(url=link_domain_str).exists():
            return Domain.objects.get(url=link_domain_str)
        else:
            return Domain.objects.create(
                url=link_domain_str,
                title=link_domain_str,
                time_discovered=timezone.now(),
                is_source="ubc.ca" in link_domain_str
                )

    async def scrape(self):
        print(" - scrape: " + self.url)
        if not "http" in self.url:
            await self.adelete()
            return

        headers = {'user-agent': 'The Society of Thoth'}

        try:
            async with aiohttp.ClientSession(headers=headers, max_line_size=8190 * 2, max_field_size=8190 * 2) as session:
                async with session.get(self.url) as r:
                    
                    soup = BeautifulSoup(await r.text(), 'html.parser')
                    
                    # Get webpage information
                    title = soup.title
                    if title != None:
                        self.title = soup.title.string

                    meta_description = soup.find("meta", attrs={"name" : "description"})
                    if meta_description == None:
                        meta_description = soup.find("meta", attrs={"property" : "og:description"})
                    if meta_description != None:
                        self.description = meta_description.get("content")

                    time_updated = None
                    meta_article_modified_time = soup.find("meta", attrs={"property" : "article:modified_time"})
                    if meta_article_modified_time != None:
                            meta_article_modified_time = meta_article_modified_time.get("content")
                            try:
                                time_updated = timezone.datetime.fromisoformat(meta_article_modified_time)
                            except:
                                print("not iso: " + meta_article_modified_time)

                    #text = soup.get_text().lower().replace("\n", " ")
                    #while "  " in text:
                    #    text = text.replace("  ", " ")
                    #words = set(text.split(" "))

                    # Parse webpage links
                    webpage_parse = urlparse(str(r.url))
                    webpage_domain_str = webpage_parse.scheme + "://" + webpage_parse.hostname
                    webpage_domain = await Domain.objects.aget(id=self.domain_id)
                    webpage_domain.time_last_requested = self.time_last_requested
                    await webpage_domain.asave()

                    url_to_name = {}
                    def transformLink(anchor):
                        link = anchor.get("href")
                        if link == None or link == "":
                            return False

                        if link[:len("https://")] != "https://":
                            if link[:2] == "//":
                                link = "https:" + link
                            elif link[0] == "/":
                                link = webpage_domain_str + link
                            elif link[:len("http")] != "http":
                                return False
                        url = urljoin(link, urlparse(link).path)
                        if not url in url_to_name:
                            if str(anchor.string) != "":
                                url_to_name[url] = str(anchor.string)
                            elif anchor.has_attr("aria-label"):
                                url_to_name[url] = anchor.get("aria-label")
                            elif anchor.has_attr("title"):
                                url_to_name[url] = anchor.get("title")
                        return url

                    links = set(filter(lambda link: link!=False, map(transformLink, soup.find_all('a'))))

                    has_subpages = False
                    new_link = False
                    for link in links:
                        link_parse = urlparse(link)
                        if link_parse.hostname == webpage_parse.hostname and webpage_parse.path in link_parse.path and link_parse.path > webpage_parse.path:
                            has_subpages = True

                        title = link
                        if link in url_to_name:
                            title = url_to_name[link]
                        elif len(link_parse.path) > 3:
                            title = link_parse.path
                        add_link = await self.new_link(link, title)
                        new_link = new_link and add_link

                    # Decide if webpage is a source
                    if has_subpages and "ubc.ca" in self.url:
                        self.is_source = True

                    # Decide if webpage has updated
                    update_from_last_request = False
                    if self.time_last_requested!= None and new_link == True:
                        update_from_last_request = True

                        if time_updated != None:
                            if time_updated > self.time_last_requested:
                                update_from_last_request = False

                    if update_from_last_request:
                            self.time_updated = timezone.now()
                    else:
                        self.time_updated = time_updated

                    self.time_last_requested = timezone.now()
                    #print("\n\n")
                    await self.asave()

        except Exception as e: 
            print(e)
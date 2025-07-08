from django.db import models
from django.utils import timezone
from django.db.models import Q

from urllib.parse import urlparse, urljoin, parse_qs
import asyncio
import aiohttp
from asgiref.sync import async_to_sync, sync_to_async

from bs4 import BeautifulSoup
import json 
import math

from organize_webpages.models import AbstractTaggableObject

HEADER = {'user-agent': 'The Society of Thoth'}
WP_API_FIRST_PAGE_SIZE = 20
WP_API_MAX_PAGE_SIZE = 100

def crawl_worthy(url):
    return "ubc.ca" in url

def get_link_domain(link):
    link_parse = urlparse(link)
    link_domain_str = link_parse.scheme + "://" + link_parse.hostname

    if Domain.objects.filter(url=link_domain_str).exists():
        return Domain.objects.get(url=link_domain_str)
    else:
        return Domain.objects.create(
            url=link_domain_str,
            title=link_domain_str,
            time_discovered=timezone.now(),
            is_source=crawl_worthy(link_domain_str)
            )

def get_link_level(link):
    link_parse = urlparse(link)
    level = link_parse.path.count("/")
    if level > 0:
        if link_parse.path[-1] == "/":
            level = level - 1

    return level

def transform_anchor(anchor, webpage_domain_str):
    link = anchor.get("href")
    if link == None or link == "":
        return False

    # Some ubc subdomains are insecure (what the heck!)
    #link = link.replace("http://", "https://")

    if link[:len("https://")] != "https://":
        if link[:2] == "//":
            link = "https:" + link
        elif link[0] == "/":
            link = webpage_domain_str + link
        elif link[:len("http")] != "http":
            return False

    url = urljoin(link, urlparse(link).path)
    return url

@sync_to_async
def obtain_new_url(url, title, updateTitle=True, referrer=None, description=None, page_type="html", time_updated=None, time_last_requested=None, time_discovered=None):
    #print(f'start obtain {url}')
    try:
        destination = None

        is_crawl_worthy = crawl_worthy(url)
        if referrer != None:
            is_crawl_worthy = is_crawl_worthy or crawl_worthy(referrer.url)

        if not WebPage.objects.filter(url=url).exists():
            if is_crawl_worthy:

                destination = WebPage.objects.create(
                    url=url,
                    title=title,
                    description=description,
                    time_updated=time_updated,
                    time_last_requested=time_last_requested,
                    time_discovered=time_discovered,
                    page_type=page_type
                    )
        else:
            destination = WebPage.objects.get(url=url)

            if description != None or time_updated != None or time_last_requested != None:
                changes = False

                if title != None and updateTitle and destination.title != title:
                    destination.title = title
                    changes = True
                if description != None and destination.description != description:
                    destination.description = description
                    changes = True
                if time_updated != None and destination.time_updated != time_updated:
                    destination.time_updated = time_updated
                    changes = True
                if time_last_requested != None and destination.time_last_requested != time_last_requested:
                    destination.time_last_requested = time_last_requested
                    changes = True
                    
                if changes:
                    destination.save()

        if destination != None and time_updated != None:
            destination_domain = destination.domain
            if destination_domain.time_updated == None:
                destination_domain.time_updated = time_updated
                destination_domain.save()
            elif time_updated > destination_domain.time_updated:
                destination_domain.time_updated = time_updated
                destination_domain.save()

        if destination != None and referrer != None:
            if not Referral.objects.filter(source_webpage=referrer, destination_webpage=destination).exists():
                Referral.objects.create(
                    source_webpage = referrer,
                    destination_webpage = destination
                )
        #print(f'obtained {url}')
        return destination
    except Exception as e: 
        if referrer != None:
            print(f"error: {url} from {referrer.url}, {e}")            
        else:
            print(f"error: {url}, {e}")
        return None

# Create your models here.

class AbstractWebObject(AbstractTaggableObject):
    url = models.URLField(max_length=510)
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True, null=True)
    
    time_updated = models.DateTimeField(blank=True, null=True)

    time_discovered = models.DateTimeField()
    time_last_requested = models.DateTimeField(blank=True, null=True)

    is_source = models.BooleanField(default=False)
    is_redirect = models.BooleanField(default=False)

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
        HIT_TIMEOUT = timezone.timedelta(hours = 3)
        #HIT_TIMEOUT = timezone.timedelta(minutes = 1)

        time_cutoff = timezone.now() - HIT_TIMEOUT

        if not await WebPage.objects.filter(domain=self).aexists():
            await WebPage.objects.acreate(
                url=self.url,
                title=self.title,
                description=self.description,
                time_updated=self.time_updated,
                time_discovered=self.time_discovered,
                is_source=self.is_source,

                domain=self,
                level=0
                )

        crawlpage_query = WebPage.objects.filter(Q(domain=self), Q(page_type="wordpress api") | Q(page_type="wordpress api index"), Q(is_source=True, time_last_requested__lte=time_cutoff) | Q(time_last_requested=None))
        hit_query = WebPage.objects.filter(Q(domain=self), Q(is_source=True, time_last_requested__lte=time_cutoff) | Q(time_last_requested=None))
        
        tasks = []
        if await crawlpage_query.aexists():
            tasks = tasks + [asyncio.create_task(wp.hit()) async for wp in crawlpage_query.order_by('level', 'time_last_requested', '-time_updated')]

        if await hit_query.aexists():
            tasks = tasks + [asyncio.create_task(wp.hit()) async for wp in hit_query.order_by('level', 'time_last_requested', '-time_updated')[:HIT_COUNT]]

        return tasks
    
class WebPageManager(models.Manager):
    def create(self, **obj_data):
        if not 'domain' in obj_data:
            obj_data['domain'] = get_link_domain(obj_data['url'])
        if not 'time_discovered' in obj_data:
            obj_data['time_discovered'] = timezone.now()
        if not 'level' in obj_data:
            obj_data['level'] = get_link_level(obj_data['url'])
        
        return super().create(**obj_data)

class WebPage(AbstractWebObject):
    domain = models.ForeignKey(Domain, related_name="webpages", on_delete=models.CASCADE)
    level = models.IntegerField(default=0)
    page_type = models.CharField(max_length=50, default="html")

    objects = WebPageManager()

    async def hit(self):
        print(" - hit: " + self.url)
        if not "http" in self.url:
            await self.adelete()
            return
        impostors = WebPage.objects.filter(domain_id=self.domain_id, url=self.url).exclude(id=self.id)
        if await impostors.aexists():
            async for impostor in impostors:
                print(f' delete: {impostor.url}')
                await impostor.adelete()

        if self.page_type == "wordpress api":
            if "?page=1&per_page=" in self.url and not f"?page=1&per_page={WP_API_FIRST_PAGE_SIZE}" in self.url:
                self.url = self.url.split("?page=1")[0] + f"?page=1&per_page={WP_API_FIRST_PAGE_SIZE}&orderby=modified&order=desc"
                await self.asave()
                print(f"fixed {self.url}")

        #try:
        async with aiohttp.ClientSession(headers=HEADER, max_line_size=8190 * 2, max_field_size=8190 * 2) as session:
            async with session.get(self.url) as r:
                requested_page = None
                text = await r.text()
                url = str(r.url)

                if url == self.url:
                    requested_page = self
                else:
                    self.is_redirect = True
                    await self.asave()
                    if self.level==0:
                        domain = await Domain.objects.aget(id=self.domain_id)
                        if not domain.url in url: 
                            domain.is_redirect = True
                            await domain.asave()

                    redirect_webpage = await obtain_new_url(url, title=self.title, page_type=self.page_type, time_discovered=self.time_discovered)
                    if redirect_webpage != None:
                        requested_page = redirect_webpage

                if requested_page != None:
                    if requested_page.page_type == "wordpress api":
                        await requested_page.wp_page_api(text)
                    elif requested_page.page_type == "wordpress api index":
                        await requested_page.wp_page_api_index(text)
                    elif requested_page.page_type == "html":
                        await requested_page.scrape(text)
                    else:
                        print(f"oops {self.url}")
                    
        #except Exception as e: 
        #    print(f"error: {self.url}, {e}")

    async def wp_page_api_index(self, text):
        print(f' - read: {self.url}')

        info = json.loads(text)

        if type(info) == dict:
            if "code" in info:
                if info["code"] == "rest_post_invalid_page_number":

                    parsed = urlparse(self.url)
                    captured_value = parse_qs(parsed.query)

                    page = int(captured_value["page"][0])
                    per_page = math.floor(int(captured_value["per_page"][0]) * 0.75)
                    orderby = int(captured_value["orderby"][0])
                    order = int(captured_value["order"][0])

                    print(f"page size too high {self.url}")
                    self.url = self.url.split("?")[0] + f'?page={page}&per_page={per_page}&orderby={orderby}&order={order}'

                    await self.asave()
                    print(f"new page size {self.url}")

                    return

        webpage_domain = await Domain.objects.aget(id=self.domain_id)
        self.time_last_requested = timezone.now()

        @sync_to_async
        def add_wp_api_page(api):
            if f"/wp/v2/{api}" in info["routes"]:
                api_page = webpage_domain.url + f"/wp-json/wp/v2/{api}?page=1&per_page={WP_API_FIRST_PAGE_SIZE}&orderby=modified&order=desc"
                if not WebPage.objects.filter(domain_id=self.domain_id, url=api_page).exists():
                    print(f"yay found {api} at {self.url}")
                    WebPage.objects.create(
                        title="Wordpress api",
                        url=api_page,
                        domain=webpage_domain,
                        page_type = "wordpress api",
                        is_source=True,
                        time_discovered=self.time_last_requested,
                        )
                    
        for api in ["pages", "posts", "media", "tribe_events"]:
            await add_wp_api_page(api)

        webpage_domain.time_last_requested = self.time_last_requested
        await self.asave()
        await webpage_domain.asave()

    async def wp_page_api(self, text):
        self.time_last_requested = timezone.now()

        print(f' - read: {self.url}')       
        pages = json.loads(text)

        tasks = []
        for page in pages:
            tasks.append(asyncio.create_task(self.wp_page_api_read_item(page)))
        print(f"start {self.url}")
        await asyncio.gather(*tasks)
        print(f"end {self.url}")

        parsed = urlparse(self.url)
        captured_value = parse_qs(parsed.query)

        if len(pages) >= int(captured_value["per_page"][0]):
            increment = int(captured_value["page"][0]) + 1

            if f"&offset={WP_API_FIRST_PAGE_SIZE}" in self.url:
                increment_url = self.url.replace(f"?page={captured_value['page'][0]}", f"?page={increment}")
            else:
                increment_url = self.url.replace(f"per_page={WP_API_FIRST_PAGE_SIZE}", f"per_page={WP_API_MAX_PAGE_SIZE}") + f"&offset={WP_API_FIRST_PAGE_SIZE}"
            print(f"increment? {increment_url}")
            if not await WebPage.objects.filter(domain_id=self.domain_id, url=increment_url).aexists():
                await WebPage.objects.acreate(
                    title=f"Wordpress api {increment}",
                    url=increment_url,
                    domain_id=self.domain_id,
                    page_type = "wordpress api",
                    is_source=False,
                    time_discovered=self.time_last_requested
                    )

        await self.asave()

    async def wp_page_api_read_item(self, page):
        if "media_type" in page:
            if page["media_type"] != "file":
                return

        description = ""

        if "excerpt" in page:
            soup = BeautifulSoup(page["excerpt"]["rendered"], "html.parser")
            description = soup.get_text()
        elif "caption" in page:
            description = BeautifulSoup(page["caption"]["rendered"], "html.parser").get_text()

        title = BeautifulSoup(page["title"]["rendered"], "html.parser").get_text()
        if title == None:
            title = page["guid"]["rendered"]

        time_updated = timezone.make_aware(timezone.datetime.fromisoformat(page["modified"]))

        listed_page = await obtain_new_url(
            page["link"], 
            title, 
            description=description,
            time_updated=time_updated,
            time_last_requested=self.time_last_requested,
            time_discovered=self.time_last_requested,
            )
            
        if "content" in page:
            webpage_parse = urlparse(self.url)
            webpage_domain_str = webpage_parse.scheme + "://" + webpage_parse.hostname

            anchors = BeautifulSoup(page["content"]["rendered"], "html.parser").find_all('a')
            
            tasks = []
            
            for anchor in anchors:
                url = transform_anchor(anchor, webpage_domain_str)
                if url != False:
                    title = anchor.string
                    if title == None or title == "":
                        title = url
                    tasks.append(asyncio.create_task(obtain_new_url(url, title, updateTitle=False, referrer=listed_page, time_discovered=self.time_last_requested)))

            await asyncio.gather(*tasks)

    async def scrape(self, text):

        print(f' - start scrape: {self.url}')
        
        soup = BeautifulSoup(text, 'html.parser')
        
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
        webpage_parse = urlparse(self.url)
        webpage_domain_str = webpage_parse.scheme + "://" + webpage_parse.hostname
        webpage_domain = await Domain.objects.aget(id=self.domain_id)

        url_to_name = {}
        def transformLink(anchor):
            url = transform_anchor(anchor, webpage_domain_str)
            if url == False or url==self.url:
                return False
                
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
        discover_time = timezone.now()
        for link in links:
            link_parse = urlparse(link)
            if link_parse.hostname == webpage_parse.hostname and webpage_parse.path in link_parse.path and link_parse.path > webpage_parse.path:
                has_subpages = True

            title = link
            if link in url_to_name:
                title = url_to_name[link]
            elif len(link_parse.path) > 3:
                print(f'name?? {link_parse.path}')
                title = link_parse.path
                print(title)

            obtained_webpage = await obtain_new_url(link, title, updateTitle=False, referrer=self, time_discovered=discover_time)
            if obtained_webpage != None:
                new_link = new_link and obtained_webpage.time_discovered==discover_time

        # Decide if webpage is a source
        if has_subpages and crawl_worthy(self.url):
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

        webpage_domain.time_last_requested = self.time_last_requested

        if self.time_updated != None:
            if webpage_domain.time_updated != None:
                if webpage_domain.time_updated < self.time_updated:
                    webpage_domain.time_updated = self.time_updated
            else:
                webpage_domain.time_updated = self.time_updated

        if self.level == 0:
            webpage_domain.description = self.description
            webpage_domain.title = self.title.replace("Home - ", "").replace("Home | ", "").replace("Home Page | ", "")
            og_site_name = soup.find("meta", attrs={"property" : "og:site_name"})

            if og_site_name != None:
                webpage_domain.title = og_site_name.get("content")

            @sync_to_async
            def add_wp_index_page():
                if "/wp-json/wp/v2/" in text:
                    if not WebPage.objects.filter(domain=webpage_domain, page_type="wordpress api index").exists():
                        print(f"created index page {webpage_domain.url + '/wp-json/wp/v2/'}")
                        WebPage.objects.create(
                            title="Wordpress api index page",
                            url=webpage_domain.url + "/wp-json/wp/v2/",
                            domain=webpage_domain,
                            page_type = "wordpress api index",
                            is_source=False,
                            time_discovered=self.time_last_requested,
                            )
            
            await add_wp_index_page()

        await webpage_domain.asave()

        await self.asave()

        print(f' - end scrape: {self.url}')

class ReferralManager(models.Manager):
    def create(self, **obj_data):
        if not 'source_domain' in obj_data:
            obj_data['source_domain'] = obj_data['source_webpage'].domain
        if not 'destination_domain' in obj_data:
            obj_data['destination_domain'] = obj_data['destination_webpage'].domain
        if not 'time_discovered' in obj_data:
            obj_data['time_discovered'] = timezone.now()
        return super().create(**obj_data)

class Referral(models.Model):
    source_webpage = models.ForeignKey(WebPage, related_name="referrs_to", on_delete=models.CASCADE)
    destination_webpage = models.ForeignKey(WebPage, related_name="referrs_from", on_delete=models.CASCADE)

    source_domain = models.ForeignKey(Domain, related_name="referrs_to", on_delete=models.CASCADE)
    destination_domain = models.ForeignKey(Domain, related_name="referrs_from", on_delete=models.CASCADE)

    time_discovered = models.DateTimeField()

    objects = ReferralManager()
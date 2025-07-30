from django.db import models
from django.utils import timezone
from django.db.models import Q

from pgvector.django import VectorField
from sentence_transformers import SentenceTransformer

from urllib.parse import urlparse, urljoin, parse_qs
import asyncio
import aiohttp
from asgiref.sync import async_to_sync, sync_to_async

from io import BytesIO
from pypdf import PdfReader
from bs4 import BeautifulSoup
import json 
import math

from thoth.settings import SIMILARITY_MODEL
from organize_webpages.models import AbstractTaggableObject

HEADER = {'user-agent': 'The Society of Thoth'}
WP_API_FIRST_PAGE_SIZE = 20
WP_API_MAX_PAGE_SIZE = 100

def crawl_worthy(url):
    return "ubc.ca" in url

def count_path_segments(link):
    '''
    Count the path segments. The root is considered to be level 0
    '''
    link_parse = urlparse(link)
    level = link_parse.path.count("/")
    if level > 0:
        if link_parse.path[-1] == "/":
            level = level - 1

    return level

def get_absolute_url(url, root_url):
    '''
    Transform 'url' into absolute url if a relative url
    '''

    if url == None or url == "":
        return False

    # Some ubc subdomains are insecure (what the heck!)
    #link = link.replace("http://", "https://")

    if url[:len("https://")] != "https://":
        if url[:2] == "//":
            url = "https:" + url
        elif url[0] == "/":
            url = root_url + url
        elif url[:len("http")] != "http":
            return False

    url = urljoin(url, urlparse(url).path)
    return url

def read_last_modified_header(r):        
    # USE Last-Modified HEADER AS PUBLISH DATE IF BEFORE DISCOVER TIME
    if "Last-Modified" in r.headers.keys():
        modified = timezone.datetime.strptime(r.headers.get("Last-Modified"), '%a, %d %b %Y %H:%M:%S GMT')
        modified = modified.replace(tzinfo=timezone.get_current_timezone())
        return modified

    return None


# Create your models here.

class AbstractWebObject(AbstractTaggableObject):
    url = models.URLField(max_length=510)
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True, null=True)
    image = models.URLField(max_length=510, blank=True, null=True)
    
    time_published = models.DateTimeField(blank=True, null=True)
    time_updated = models.DateTimeField(blank=True, null=True)

    time_discovered = models.DateTimeField()
    time_last_requested = models.DateTimeField(blank=True, null=True)

    is_source = models.BooleanField(default=False)
    is_redirect = models.BooleanField(default=False)

    def __str__(self):
        return self.url

    class Meta():
        abstract = True

class DomainManager(models.Manager):
    def get_domain_from_url(self, link, create_if_not_existing=True):
        '''
        Obtain a domain model from a url. If the domain does not exist in the database, create it.
        '''
        link_parse = urlparse(link)

        if not "http" in link_parse.scheme or link_parse.hostname == None:
            return None

        link_domain_str = link_parse.scheme + "://" + link_parse.hostname
        safe_domain = link_domain_str.replace("http://", "https://")

        if Domain.objects.filter(url=safe_domain).exists():
            return Domain.objects.filter(url=safe_domain).first()
        if Domain.objects.filter(url=link_domain_str).exists():
            return Domain.objects.filter(url=link_domain_str).first()
        elif create_if_not_existing: 
            return Domain.objects.create(
                url=link_domain_str,
                title=link_domain_str,
                time_discovered=timezone.now(),
                is_source=crawl_worthy(link_domain_str)
                )

        return None

class Domain(AbstractWebObject):
    robots_txt = models.TextField(blank=True, null=True)
    time_last_checked_robots_txt = models.DateTimeField(blank=True, null=True)

    objects = DomainManager()

    def check_robots_txt(self):
        pass

    async def get_webpage_to_hit(self):
        #print("domain: " + self.url)
        HIT_COUNT = 5
        #HIT_TIMEOUT = timezone.timedelta(hours = 3)
        HIT_TIMEOUT = timezone.timedelta(minutes = 1)

        time_cutoff = timezone.now() - HIT_TIMEOUT

        self.time_last_requested = timezone.now()

        await self.asave()

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

            #print(f"create homepage {self.url}")

        crawlpage_query = WebPage.objects.filter(Q(domain=self), Q(page_type="wordpress api") | Q(page_type="wordpress api index"), Q(is_source=True, time_last_requested__lte=time_cutoff) | Q(time_last_requested=None))
        hit_query = WebPage.objects.filter(Q(domain=self), Q(is_source=True, time_last_requested__lte=time_cutoff) | Q(time_last_requested=None))
        tasks = []

        '''
        if await crawlpage_query.aexists():
            tasks = tasks + [asyncio.create_task(wp.hit()) async for wp in crawlpage_query.order_by('level', 'time_last_requested', '-time_updated')]

        if await hit_query.aexists():
            tasks = tasks + [asyncio.create_task(wp.hit()) async for wp in hit_query.order_by('level', 'time_last_requested', '-time_updated')[:HIT_COUNT]]
        '''

        if await crawlpage_query.aexists():
            tasks = tasks + [await wp.hit() async for wp in crawlpage_query.order_by('level', 'time_last_requested', '-time_updated')]

        if await hit_query.aexists():
            tasks = tasks + [await wp.hit() async for wp in hit_query.order_by('level', 'time_last_requested', '-time_updated')[:HIT_COUNT]]

        return tasks
    
class WebPageManager(models.Manager):
    def create(self, **obj_data):
        if not 'domain' in obj_data:
            obj_data['domain'] = Domain.objects.get_domain_from_url(obj_data['url'])
        if not 'time_discovered' in obj_data:
            obj_data['time_discovered'] = timezone.now()
        if not 'level' in obj_data:
            obj_data['level'] = count_path_segments(obj_data['url'])

        if "https://" in obj_data['domain'].url and not "https://" in obj_data['url']:
            obj_data['url'] = obj_data['url'].replace("http://", "https://")
        
        return super().create(**obj_data)

    def obtain_webpage(self, url, title, time_discovered=None):
        '''
        Return WebPage object with specific url if existing, setup one up if not 
        '''

        if time_discovered == None:
            time_discovered = timezone.now()
        
        destination = None

        if not WebPage.objects.filter(url=url).exists():
            if WebPage.objects.filter(url=url.replace("http://", "https://")).exists():
                url = url.replace("http://", "https://")
                #print(f' secure {url}')
            else:

                domain = Domain.objects.get_domain_from_url(url)

                if domain == None:
                    return None

                if "https://" in domain.url and not "https://" in url:
                    url = url.replace("http://", "https://")

                return WebPage(
                    domain=domain,
                    url=url,
                    title=title,
                    time_discovered=time_discovered,
                    level=count_path_segments(url),
                    )
        
        return WebPage.objects.filter(url=url).first()

    async def aobtain_webpage(self, url, title, time_discovered=timezone.now()):
        return await sync_to_async(self.obtain_webpage)(url, title, time_discovered)


class WebPage(AbstractWebObject):
    domain = models.ForeignKey(Domain, related_name="webpages", on_delete=models.CASCADE)
    level = models.IntegerField(default=0)
    page_type = models.CharField(max_length=50, default="html")

    objects = WebPageManager()

    async def update(self, **kwargs):
        '''
        Update webpage if attributes are changed or model is unsaved.
        Save embedding if title is updated.
        '''

        changes = False
        # Update Webpage if attributes have changed
        for attribute in vars(self).keys():
            if attribute in kwargs:

                if getattr(self, attribute) != kwargs[attribute]:
                    setattr(self, attribute, kwargs[attribute])
                    changes = True
                
                    if attribute == "title":
                        await Embeddings.objects.aencode(string=self.title, webpage=self, source_attribute="title")

        if changes or self._state.adding == True:
            await self.asave()

        print(f'      - updated {self.url}')
        return self

    async def judge_destination_crawl_worthy(self, destinations):
        domain = await Domain.objects.aget(id=self.domain_id)

        async def judge_destination(destination):
            if len(destination) > 510:
                print(f'too long {destination}')
                return False

            is_crawl_worthy = crawl_worthy(destination) or crawl_worthy(self.url)

            if not is_crawl_worthy:
                is_crawl_worthy = domain.is_source
                
                if not is_crawl_worthy and not domain.url in destination: 
                    destination_domain = await sync_to_async(Domain.objects.get_domain_from_url)(destination, create_if_not_existing=False)
                    if destination_domain:
                        is_crawl_worthy = destination_domain.is_source
            
            return is_crawl_worthy

        worthy = []
        for d in destinations:
            if await judge_destination(d):
                worthy.append(d)

        return worthy

    async def hit(self):
        print(" - hit: " + self.url)
        hit_time = timezone.now()
        if not "http" in self.url:
            await self.adelete()
            return

        try:
            async with aiohttp.ClientSession(headers=HEADER, max_line_size=8190 * 2, max_field_size=8190 * 2) as session:
                async with session.get(self.url) as r:
                    #print(f' - HITTED ({timezone.now() - hit_time})\n    - {self.url}')
                    
                    requested_page = None
                    url = str(r.url)

                    if url == self.url:
                        requested_page = self
                    else:
                        self.is_redirect = True
                        self.time_last_requested = timezone.now()
                        await self.asave()
                        if self.level==0:
                            domain = await Domain.objects.aget(id=self.domain_id)
                            if not domain.url in url: 
                                domain.is_redirect = True
                                await domain.asave()

                        if len(await self.judge_destination_crawl_worthy([url])) > 0:
                            redirect_webpage = await WebPage.objects.aobtain_webpage(url, self.title)
                            if redirect_webpage != None:
                                requested_page = redirect_webpage

                    if requested_page != None:
                        if requested_page.page_type == "wordpress api":
                            await requested_page.wp_page_api(r)
                        elif requested_page.page_type == "wordpress api index":
                            await requested_page.wp_page_api_index(r)
                        else:
                            if "pdf" in r.content_type:
                                await self.scrape_pdf(r)
                            elif "html" in r.content_type:
                                await requested_page.scrape(r)
                            else:
                                print(f" - WEIRD CONTENT TYPE {r.content_type} oops {self.url} ")
                                requested_page.time_last_requested = timezone.now()
                                await requested_page.asave()

                    print(f" - hitted: {self.url}")
                    return requested_page
                        
        except Exception as e: 
            print(f"error: {self.url}, {e}")
            return None

    def read_anchors(self, anchors):
        referrer_url_parse = urlparse(self.url)
        referrer_domain_str = referrer_url_parse.scheme + "://" + referrer_url_parse.hostname

        urls = []
        titles = {}
        for anchor in anchors:
            url = anchor.get("href")
            if url == None or url == "":
                continue
            url = get_absolute_url(url, referrer_domain_str)
            if url != False:
                if anchor.string != "" and anchor.string != None:
                    title = anchor.string
                elif anchor.has_attr("aria-label"):
                    title = anchor.get("aria-label")
                elif anchor.has_attr("title"):
                    title = anchor.get("title")
                else:
                    title = url

                if not url in urls:
                    urls.append(url)
                if not url in titles:
                    titles[url] = title
                elif titles[url].count(" ") < title.count(" "):
                    titles[url] = title
        
        return urls, titles

    async def deal_with_hyperlinks(self, links, link_labels):
        subpages = False
        new_links = False

        start = timezone.now()
        now = timezone.now()

        @sync_to_async
        def get_or_create_pages(urls, titles):
            global subpages, new_links

            start = timezone.now()
            webpages_from_hyperlinks = []
            for url in urls:
                if url != self.url and url in self.url:
                    subpages = True

                if not url in titles:
                    titles[url] = url 
            
            urls = async_to_sync(self.judge_destination_crawl_worthy)(urls)
            print(f'            - judge crawlworthy {self.url}')
            webpages_from_hyperlinks = [WebPage.objects.obtain_webpage(url, titles[url], time_discovered=now) for url in urls]
            print(f'            - obtain {self.url}')
            webpages_from_hyperlinks = list(filter(lambda wp: wp!= None, webpages_from_hyperlinks))
            webpages_to_create = list(filter(lambda wp: wp._state.adding == True, webpages_from_hyperlinks))
            #print(f'            - filter by adding {self.url}')

            if len(webpages_to_create) > 0:
                print(f'            - bulk create {self.url}')
                new_links = True
                WebPage.objects.bulk_create(webpages_to_create)
                print(f'            - bulk created {self.url}')

            return webpages_from_hyperlinks

        async def create_new_referrs(webpages):
            start = timezone.now()
            referals = []
            print(f'                        - start create refers {self.url} {len(webpages)}')
            for webpage in webpages:
                if not await Referral.objects.filter(source_webpage=self, destination_webpage=webpage).aexists():
                    print(f'                        - setup refers {self.url} {webpage.url}')
                    referals.append(Referral(
                        source_webpage = self,
                        source_domain_id = self.domain_id,

                        destination_webpage = webpage,
                        destination_domain_id = webpage.domain_id,

                        time_discovered = now
                        ))

            print(f'            - create refers start {self.url}')
            await Referral.objects.abulk_create(referals)
            print(f'            - create refers finish {self.url}')

        print(f'      - create pages {self.url}  {len(links)}')
        webpages = await get_or_create_pages(links, link_labels)
        print(f'      - create refers {self.url} {len(webpages)}')
        await create_new_referrs(webpages)
        return subpages, new_links

    async def wp_page_api_test(self, wp_api_a, wp_api_b):
        # Wordpress api can be messed up sometimes.
        # This allows us to test that the parameters we are using are all fine in combination
        # Do not save api requests with untested parameter combinations 

        async def async_web_request(url):
            async with aiohttp.ClientSession(headers=HEADER, max_line_size=8190 * 2, max_field_size=8190 * 2) as session:
                async with session.get(url) as r:
                    return json.loads(await r.text())

        a, b = await asyncio.gather(async_web_request(wp_api_a), async_web_request(wp_api_b))

        if type(a) == list and type(b) == list:
            if a[0] != b[0]:
                return 0
            else:
                print("not paging correctly")
                return 1
        else:
            if type(a) == type(b):
                print("error with api")
                print(a)
                print(b)
                return 2

            elif type(a) != list:
                print("error on first page")
                print(a)

                return 3

            else:
                print("error on second page")
                print(b)
                return 4

    async def wp_page_api_index(self, r):

        text = await r.text()

        API_ROUTES = ["pages", "posts", "media", "tribe_events"]

        #print(f' - read: {self.url}')

        info = json.loads(text)

        webpage_domain = await Domain.objects.aget(id=self.domain_id)
        self.time_last_requested = timezone.now()

        possible_api_routes = [
            lambda api, i, pp: webpage_domain.url + f"/wp-json/wp/v2/{api}?page={i}&per_page={pp}&orderby=modified&order=desc",
            lambda api, i, pp: webpage_domain.url + f"/wp-json/wp/v2/{api}?offset={(i-1)*pp}&per_page={pp}&orderby=modified&order=desc",
            lambda api, i, pp: webpage_domain.url + f"/wp-json/wp/v2/{api}?page={i}&per_page={pp}&order=desc",
            lambda api, i, pp: webpage_domain.url + f"/wp-json/wp/v2/{api}?offset={(i-1)*pp}&per_page={pp}&order=desc",
            lambda api, i, pp: webpage_domain.url + f"/wp-json/wp/v2/{api}?page={i}&per_page={pp}&orderby=modified",
            lambda api, i, pp: webpage_domain.url + f"/wp-json/wp/v2/{api}?offset={(i-1)*pp}&per_page={pp}&orderby=modified",
            lambda api, i, pp: webpage_domain.url + f"/wp-json/wp/v2/{api}?page={i}&per_page={pp}",
            lambda api, i, pp: webpage_domain.url + f"/wp-json/wp/v2/{api}?offset={(i-1)*pp}&per_page={pp}",
        ]

        @sync_to_async
        def add_wp_api_page(api, pa):
            if f"/wp/v2/{api}" in info["routes"]:
                api_page = possible_api_routes[pa](api, 1, WP_API_FIRST_PAGE_SIZE)
                if not WebPage.objects.filter(domain_id=self.domain_id, url=api_page).exists():
                    print(f" - {self.url} wp api found {api}")
                    WebPage.objects.create(
                        title="Wordpress api",
                        url=api_page,
                        domain=webpage_domain,
                        page_type = "wordpress api",
                        is_source=True,
                        time_discovered=self.time_last_requested,
                        )

        pa = 0
        for api in API_ROUTES:
            if f"/wp/v2/{api}" in info["routes"]:
                print(f'testing with {api}')

                a = 1
                b = 2

                while True:
                    if pa > len(possible_api_routes):
                        pa = 0
                        print(f'exhuasted possibilities')
                        break

                    #try:
                    test_result = await self.wp_page_api_test(possible_api_routes[pa](api, a, 1), possible_api_routes[pa](api, b, 1))

                    if test_result == 0:
                        print(f"suceeded with {possible_api_routes[pa](api, a, 1)} {possible_api_routes[pa](api, b, 1)}")
                        break
                    elif test_result == 1:
                        pa = pa + 1
                    elif test_result == 2:
                        pa = pa + 1
                    elif test_result == 3:
                        a = b
                        b = b + 1
                    elif test_result == 4:
                        b = b + 1
                    
                    #except:
                    #    print(f"error requesting {possible_api_routes[pa](api, a, 1)} {possible_api_routes[pa](api, b, 1)}")
                    #    pa = 0
                    #    break
                break

        for api in API_ROUTES:
            await add_wp_api_page(api, pa)

        webpage_domain.time_last_requested = self.time_last_requested
        await self.asave()
        await webpage_domain.asave()


    async def wp_page_api(self, r):
        text = await r.text()

        self.time_last_requested = timezone.now()

        #print(f' - read: {self.url}')       
        info = json.loads(text)

        if type(info) == dict:
            if "code" in info:
                if info["code"] == "rest_invalid_param":
                    if info["message"] == "Invalid parameter(s): per_page":
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

                elif info["code"] == "rest_post_invalid_page_number":
                    print(f"delete {self.url}")
                    await self.adelete()

                return
        
        pages = info
        #print(f"pages ({len(pages)}) {self.url}")
        tasks = []
        print(F"TO GATHER {self.url}")
        for page in pages:
            #tasks.append(asyncio.create_task(self.wp_page_api_read_item(page)))
            await self.wp_page_api_read_item(page)
        
        add_wp_articles_time = timezone.now()
        #await asyncio.gather(*tasks)
        print(F"GATHERED {self.url}")
        print(f' - WP PAGES ({len(pages)}) ({timezone.now() - add_wp_articles_time})\n    - {self.url}')

        parsed = urlparse(self.url)
        captured_value = parse_qs(parsed.query)

        if len(pages) >= int(captured_value["per_page"][0]):

            increment = None
            increment_url = None

            if int(captured_value['per_page'][0]) > WP_API_FIRST_PAGE_SIZE:
                if "page" in captured_value:                
                    increment = int(captured_value["page"][0]) + 1
                    increment_url = self.url.replace(f"?page={captured_value['page'][0]}", f"?page={increment}")
                elif "offset" in captured_value:
                    increment = int(captured_value["offset"][0]) + int(captured_value["per_page"][0])
                    increment_url = self.url.replace(f"?offset={captured_value['offset'][0]}", f"?offset={increment}")

            else:
                increment_url = self.url.replace(f"per_page={WP_API_FIRST_PAGE_SIZE}", f"per_page={WP_API_MAX_PAGE_SIZE}")
            
            if increment_url != None:
                #print(f"increment? {increment_url}")
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
            if not page["media_type"] in ["file", "application", "video", "audio"]:
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

        image = None
        if "yoast_head_json" in page:
            if "og_image" in page["yoast_head_json"]:
                if len(page["yoast_head_json"]["og_image"]) > 0:
                    image = page["yoast_head_json"]["og_image"][0]["url"]

        time_updated = timezone.make_aware(timezone.datetime.fromisoformat(page["modified"]))

        listed_page = await WebPage.objects.aobtain_webpage(page["link"], title)


        if listed_page == None:
            return

        print(f'      - to update item {listed_page.url}')

        await listed_page.update(
            title=title, 
            description=description,
            image=image,
            time_updated=time_updated,
            time_last_requested=self.time_last_requested,
            )

        if listed_page:
                
            if "content" in page:
                anchors = BeautifulSoup(page["content"]["rendered"], "html.parser").find_all('a')
                links, link_labels = listed_page.read_anchors(anchors)
                print(f'      - read anchors {listed_page.url}')
                await listed_page.deal_with_hyperlinks(links, link_labels)
                print(f'      - deal with hyperlinks {listed_page.url}')
        
        print(f'      - read item {listed_page.url}')

    async def scrape(self, r):
        
        text = await r.text()

        start_scrape_time = timezone.now()

        start_time = timezone.now()
        soup = BeautifulSoup(text, 'html.parser')
        print(f'      - soup ({timezone.now() - start_time})\n    - {self.url}')
        
        # SCRAPE INFORMATION FROM WEBPAGE

        ### Scrape 'time_updated' and 'time_published' from yoast schema graph if existing
        time_updated = None
        yoast_graph = soup.find("script", attrs={"type" : "application/ld+json", "class": "yoast-schema-graph"})
        if yoast_graph != None:
            yoast_graph = json.loads(yoast_graph.decode_contents())
            if "@graph" in yoast_graph:
                for scheme in yoast_graph["@graph"]:
                    if "@type" in scheme:
                        if scheme["@type"] == "WebPage":
                            if "dateModified" in scheme:
                                time_updated = timezone.datetime.fromisoformat(scheme["dateModified"])

                            if "datePublished" in scheme:
                                self.time_published = timezone.datetime.fromisoformat(scheme["datePublished"])
                            break

        ### Scrape title of webpage
        title = soup.find("meta", attrs={"property" : "og:title"})
        if title != None:
            title = title.get("content")
        else:
            title = soup.title
            if title != None:
                title = soup.title.string

        if title != None:
            if not await self.embeddings.filter(source_attribute="title").aexists() or self.title != title:
                await Embeddings.objects.aencode(string=title, webpage=self, source_attribute="title")
            self.title = title

        ### Scrape description of webpage
        meta_description = soup.find("meta", attrs={"name" : "description"})
        if meta_description == None:
            meta_description = soup.find("meta", attrs={"property" : "og:description"})
        if meta_description != None:
            self.description = meta_description.get("content")

        ### Scrape image of webpage
        meta_image = soup.find("meta", attrs={"property" : "og:image"})
        if meta_image == None:
            meta_image = soup.find("meta", attrs={"name" : "twitter:image"})
        if meta_image != None:
            self.image = meta_image.get("content")

        ### Scrape article modified time of webpage
        meta_article_publish_time = soup.find("meta", attrs={"property" : "article:published_time"})
        if meta_article_publish_time != None:
            meta_article_publish_time = meta_article_publish_time.get("content")
            try:
                self.time_published = timezone.datetime.fromisoformat(meta_article_publish_time)
            except:
                print("not iso: " + meta_article_publish_time)

        ### Scrape article modified time of webpage
        meta_article_modified_time = soup.find("meta", attrs={"property" : "article:modified_time"})
        if meta_article_modified_time != None:
            meta_article_modified_time = meta_article_modified_time.get("content")
            try:
                time_updated = timezone.datetime.fromisoformat(meta_article_modified_time)
            except:
                print("not iso: " + meta_article_modified_time)

        if self.time_published == None:
            last_modified_header = read_last_modified_header(r)
            if last_modified_header:
                if last_modified_header < self.time_discovered:
                    self.time_published = last_modified_header
                        
        print(f'      - saved meta {self.url}')
        #text = soup.get_text().lower().replace("\n", " ")
        #while "  " in text:
        #    text = text.replace("  ", " ")
        #words = set(text.split(" "))

        # COLLECT AND PROCESS HYPERLINKS
        anchors = soup.find_all('a')
        links, link_labels = self.read_anchors(anchors)
        subpages, new_links = await self.deal_with_hyperlinks(links, link_labels)

        print(f'      - dealt with hyperlinks {self.url}')
        
        # Decide if webpage has updated
        update_from_last_request = False
        if self.time_last_requested!= None and new_links:
            update_from_last_request = True

            if time_updated != None:
                if time_updated > self.time_last_requested:
                    update_from_last_request = False
        
        if update_from_last_request:
                self.time_updated = timezone.now()
        elif time_updated != None:
            self.time_updated = time_updated.replace(tzinfo=timezone.get_current_timezone())
        
        webpage_domain = await Domain.objects.aget(id=self.domain_id)
        # Decide if webpage is a source
        if subpages and webpage_domain.is_source:
            self.is_source = True

        self.time_last_requested = timezone.now()

        webpage_domain.time_last_requested = self.time_last_requested

        if self.time_updated != None:
            if webpage_domain.time_updated != None:
                if webpage_domain.time_updated < self.time_updated:
                    webpage_domain.time_updated = self.time_updated
            else:
                webpage_domain.time_updated = self.time_updated
        elif self.time_published:
            self.time_updated = self.time_published

        if self.level == 0:
            webpage_domain.description = self.description
            homepage_names = ["Home :: ", "Home - ", "Home | ", "Home Page | ", "Front Page | ", "Homepage | ", "Welcome | "]
            webpage_domain.title = self.title
            for homepage_name in homepage_names:
                webpage_domain.title = webpage_domain.title.replace(homepage_name, "")

            og_site_name = soup.find("meta", attrs={"property" : "og:site_name"})

            if og_site_name != None:
                webpage_domain.title = og_site_name.get("content")


            def get_icon_size(icon):
                if icon.get("sizes") != None:
                    return int(icon.get("sizes").split("x")[0])
                else:
                    return 0


            web_domain_image = None
            apple_icons = soup.find_all("link", attrs={"rel" : "apple-touch-icon"})
            if len(apple_icons) > 0:
                web_domain_image = sorted(apple_icons, key=get_icon_size, reverse=True)[0]

            if web_domain_image == None:
                apple_icons = soup.find_all("link", attrs={"rel" : "apple-touch-icon-precomposed"})
                if len(apple_icons) > 0:
                    web_domain_image = sorted(apple_icons, key=get_icon_size, reverse=True)[0]

            if web_domain_image == None:
                web_domain_image = soup.find("link", attrs={"rel" : "shortcut icon"})
                if web_domain_image != None:
                    web_domain_image = web_domain_image

            if web_domain_image == None:
                icons = soup.find_all("link", attrs={"rel" : "icon"})
                if len(icons) > 0:
                    web_domain_image = sorted(icons, key=get_icon_size, reverse=True)[0]

            if web_domain_image != None:
                web_domain_image_url = web_domain_image.get("href")
                if web_domain_image_url != None or web_domain_image_url != "":                  

                    web_domain_image = get_absolute_url(web_domain_image_url, webpage_domain.url)

                    webpage_domain.image = web_domain_image

            @sync_to_async
            def add_wp_index_page():
                if "/wp-json/" in text or "/wp-content/" in text:
                    if not WebPage.objects.filter(domain=webpage_domain, page_type="wordpress api index").exists():
                        print(f" - {self.url} created index page {webpage_domain.url + '/wp-json/wp/v2/'}")
                        WebPage.objects.create(
                            title="Wordpress api index page",
                            url=webpage_domain.url + "/wp-json/wp/v2/",
                            domain=webpage_domain,
                            page_type = "wordpress api index",
                            is_source=False,
                            time_discovered=self.time_last_requested,
                            )
            
            await add_wp_index_page()

        print(f"save scrape {self.url}")
        await asyncio.gather(webpage_domain.asave(), self.asave())

        #print(f' - SCRAPE ({timezone.now() - start_scrape_time})\n    - {self.url}')

    async def scrape_pdf(self, r):
        print(f' - IGNORE PDF {r.url} for now')
        reader = PdfReader(BytesIO(await r.read()))

        self.time_last_requested = timezone.now()

        # USE METADATA FOR TITLE
        meta = reader.metadata
        if meta.title:
            if not await self.embeddings.filter(source_attribute="title").aexists() or self.title != meta.title:
                await Embeddings.objects.aencode(string=meta.title, webpage=self, source_attribute="title")
            self.title = meta.title


        # USE METADATA FOR DESCRIPTION FIELD
        meta_info = [
            (f"{meta.keywords}", meta.keywords),
            (f"Subject: {meta.subject}", meta.subject),
            (f"Author: {meta.author}", meta.author),
            (f"Creator: {meta.creator}", meta.creator),
            (f"Producer: {meta.producer}", meta.producer),
            (f"Created: {meta.creation_date}", meta.creation_date),
            (f"Modified: {meta.modification_date}", meta.modification_date),
        ]
        self.description = "\n".join(map(lambda info: info[0], (filter(lambda info: info[1], meta_info))))


        last_modified_header = read_last_modified_header(r)
        self.time_updated = last_modified_header
        if self.time_discovered > last_modified_header:
            self.time_published = last_modified_header


        # COLLECT AND PROCESS HYPERLINKS
        hyperlinks = []
        for i in range(reader.get_num_pages()):
            page = reader.pages[i]
            if "/Annots" in page:
                for annotation in page["/Annots"]:
                    if "/A" in annotation.get_object():
                        if annotation.get_object()["/A"]["/S"] == "/URI":
                            hyperlinks.append(annotation.get_object()["/A"]["/URI"])

        if len(hyperlinks) > 0:
            await self.deal_with_hyperlinks(hyperlinks, {})

        # READ TEXT
        #text = "\n".join([page.extract_text() for page in reader.pages])
        #print(text)

        await self.asave()


class ReferralManager(models.Manager):
    def create(self, **obj_data):
        if not 'source_domain' in obj_data:
            obj_data['source_domain'] = obj_data['source_webpage'].domain
        if not 'destination_domain' in obj_data:
            obj_data['destination_domain'] = obj_data['destination_webpage'].domain
        if not 'time_discovered' in obj_data:
            obj_data['time_discovered'] = timezone.now()
        return super().create(**obj_data)
    async def acreate(self, **obj_data):
        return await sync_to_async(self.create)(**obj_data)

class Referral(models.Model):
    source_webpage = models.ForeignKey(WebPage, related_name="referrs_to", on_delete=models.CASCADE)
    destination_webpage = models.ForeignKey(WebPage, related_name="referrs_from", on_delete=models.CASCADE)

    source_domain = models.ForeignKey(Domain, related_name="referrs_to", on_delete=models.CASCADE)
    destination_domain = models.ForeignKey(Domain, related_name="referrs_from", on_delete=models.CASCADE)

    time_discovered = models.DateTimeField()

    objects = ReferralManager()



class EmbeddingsManager(models.Manager):

    def encode(self, string, webpage, source_attribute):
        start_time = timezone.now()
        
        embedding = SIMILARITY_MODEL.encode(string)
        
        #print(f' - EMBEDDING ({source_attribute}) ({timezone.now() - start_time})\n    - {webpage.url}')

        obj_data = {
            "embedding": embedding,
            "webpage": webpage,
            "domain": webpage.domain,
            "source_attribute": source_attribute
        }

        return super().create(**obj_data)
    
    async def aencode(self, string, webpage, source_attribute):
        return await sync_to_async(self.encode)(string, webpage, source_attribute)


class Embeddings(models.Model):
    objects = EmbeddingsManager()

    embedding = VectorField(dimensions=384)

    webpage = models.ForeignKey(WebPage, related_name="embeddings", on_delete=models.CASCADE)
    domain = models.ForeignKey(Domain, related_name="embeddings", on_delete=models.CASCADE)
    source_attribute = models.CharField()

from django.db import models
from django.utils import timezone
from django.db.models import Q

from pgvector.django import VectorField
from sentence_transformers import SentenceTransformer

from urllib.parse import urlparse, urljoin, parse_qs
import asyncio
import aiohttp
from asgiref.sync import async_to_sync, sync_to_async

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

def get_link_domain(link):
    link_parse = urlparse(link)
    link_domain_str = link_parse.scheme + "://" + link_parse.hostname
    safe_domain = link_domain_str.replace("http://", "https://")

    if Domain.objects.filter(url=link_domain_str).exists():
        return Domain.objects.get(url=link_domain_str)
    elif Domain.objects.filter(url=safe_domain).exists():
        return Domain.objects.get(url=safe_domain)
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

async def obtain_new_url(url, title, updateTitle=True, referrer=None, description=None, image=None, page_type="html", time_updated=None, time_last_requested=None, time_discovered=None):
    #print(f'start obtain {url}')
    try:
        destination = None

        if len(url) > 510:
            return None

        is_crawl_worthy = crawl_worthy(url)
        if referrer != None:
            is_crawl_worthy = is_crawl_worthy or crawl_worthy(referrer.url)

        if not is_crawl_worthy:
            return None

        @sync_to_async
        def create_if_not_existing(url):
            if not WebPage.objects.filter(url=url).exists():
                if WebPage.objects.filter(url=url.replace("http://", "https://")).exists():
                    url = url.replace("http://", "https://")
                    print(f' secure {url}')
                else:
                    destination = WebPage.objects.create(
                        url=url,
                        title=title,
                        description=description,
                        image=image,
                        time_updated=time_updated,
                        time_last_requested=time_last_requested,
                        time_discovered=time_discovered,
                        page_type=page_type
                        )

                    if not destination.embeddings.filter(source_attribute="title").exists():
                        Embeddings.objects.encode(string=destination.title, webpage=destination, source_attribute="title")

                    return destination

            return WebPage.objects.get(url=url)

        destination = await create_if_not_existing(url)

        tasks = []

        attributes = [description, time_updated, time_last_requested]
        if len(list(filter(lambda attribute: attribute!=None, attributes))) > 0:
            changes = False

            if title != None and updateTitle and destination.title != title:
                destination.title = title

                if not await destination.embeddings.filter(source_attribute="title").aexists():
                    await Embeddings.objects.aencode(string=destination.title, webpage=destination, source_attribute="title")

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
            if image != None and destination.image != image:
                destination.image = image
                changes = True                    
            if changes:
                tasks.append(asyncio.create_task(destination.asave()))

        '''
        if destination != None and time_updated != None:
            destination_domain = destination.domain
            if destination_domain.time_updated == None:
                destination_domain.time_updated = time_updated
                tasks.append(destination_domain.asave())
            elif time_updated > destination_domain.time_updated:
                destination_domain.time_updated = time_updated
                tasks.append(destination_domain.asave())
        '''

        if destination != None and referrer != None:
            if not await Referral.objects.filter(source_webpage=referrer, destination_webpage=destination).aexists():
                tasks.append(asyncio.create_task(Referral.objects.acreate(
                    source_webpage = referrer,
                    destination_webpage = destination
                    )))
                
        await asyncio.gather(*tasks)

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
    image = models.URLField(max_length=510, blank=True, null=True)
    
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
        #print("domain: " + self.url)
        HIT_COUNT = 1
        #HIT_TIMEOUT = timezone.timedelta(hours = 3)
        HIT_TIMEOUT = timezone.timedelta(minutes = 1)

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

        if "https://" in obj_data['domain'].url and not "https://" in obj_data['url']:
            obj_data['url'] = obj_data['url'].replace("http://", "https://")
        
        return super().create(**obj_data)

class WebPage(AbstractWebObject):
    domain = models.ForeignKey(Domain, related_name="webpages", on_delete=models.CASCADE)
    level = models.IntegerField(default=0)
    page_type = models.CharField(max_length=50, default="html")

    objects = WebPageManager()

    async def hit(self):
        #print(" - hit: " + self.url)
        hit_time = timezone.now()
        if not "http" in self.url:
            await self.adelete()
            return

        #try:
        async with aiohttp.ClientSession(headers=HEADER, max_line_size=8190 * 2, max_field_size=8190 * 2) as session:
            async with session.get(self.url) as r:
                print(f' - HITTED ({timezone.now() - hit_time})\n    - {self.url}')
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

                return requested_page
                    
        #except Exception as e: 
        #    print(f"error: {self.url}, {e}")
        #    return None

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

    async def wp_page_api_index(self, text):
        API_ROUTES = ["pages", "posts", "media", "tribe_events"]

        print(f' - read: {self.url}')

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


    async def wp_page_api(self, text):
        self.time_last_requested = timezone.now()

        print(f' - read: {self.url}')       
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

        tasks = []
        for page in pages:
            tasks.append(asyncio.create_task(self.wp_page_api_read_item(page)))
        
        add_wp_articles_time = timezone.now()
        await asyncio.gather(*tasks)
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
            if not page["media_type"] in ["file", "application", "video", "audio"]:
                return
            else:
                print(f'whoa {page["link"]} {page["media_type"]}')

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

        listed_page = await obtain_new_url(
            page["link"], 
            title, 
            description=description,
            image=image,
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

        start_scrape_time = timezone.now()

        start_time = timezone.now()
        soup = BeautifulSoup(text, 'html.parser')
        print(f' - SOUP ({timezone.now() - start_time})\n    - {self.url}')
        
        # Get webpage information
        title = soup.title
        if title != None:
            self.title = soup.title.string

        meta_description = soup.find("meta", attrs={"name" : "description"})
        if meta_description == None:
            meta_description = soup.find("meta", attrs={"property" : "og:description"})
        if meta_description != None:
            self.description = meta_description.get("content")

        meta_image = soup.find("meta", attrs={"property" : "og:image"})
        if meta_image == None:
            meta_image = soup.find("meta", attrs={"name" : "twitter:image"})
        if meta_image != None:
            self.image = meta_image.get("content")

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
                if anchor.string != "" and anchor.string != None:
                    url_to_name[url] = anchor.string
                elif anchor.has_attr("aria-label"):
                    url_to_name[url] = anchor.get("aria-label")
                elif anchor.has_attr("title"):
                    url_to_name[url] = anchor.get("title")

            return url

        start_time = timezone.now()
        links = set(filter(lambda link: link!=False, map(transformLink, soup.find_all('a'))))
        #print(f'get anchors: {timezone.now() - start_time}')

        start_time = timezone.now()
        is_subpage = []
        new_links = []
        discover_time = timezone.now()
        
        async def add_refers(link, is_subpage, new_links):
            link_parse = urlparse(link)
            if link_parse.hostname == webpage_parse.hostname and webpage_parse.path in link_parse.path and link_parse.path > webpage_parse.path:
                is_subpage.append(True)

            title = link
            if link in url_to_name:
                title = url_to_name[link]
            elif len(link_parse.path) > 3:
                title = " ".join(filter(lambda segment: segment != " ", link_parse.path.replace("/", " ").split("-")))

            obtained_webpage = await obtain_new_url(link, title, updateTitle=False, referrer=self, time_discovered=discover_time)
            if obtained_webpage != None:
                new_links.append(obtained_webpage.time_discovered==discover_time)

        await asyncio.gather(*[add_refers(link, is_subpage, new_links) for link in links])

        print(f' - REFERS ({len(links)}) ({timezone.now() - start_time})\n    - {self.url}')

        # Decide if webpage is a source
        if True in is_subpage and crawl_worthy(self.url):
            self.is_source = True

        # Decide if webpage has updated
        update_from_last_request = False
        if self.time_last_requested!= None and True in new_links:
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
                web_domain_image = transform_anchor(web_domain_image, webpage_domain.url)

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

        await asyncio.gather(webpage_domain.asave(), self.asave())

        print(f' - SCRAPE ({timezone.now() - start_scrape_time})\n    - {self.url}')

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
        
        print(f' - EMBEDDING ({source_attribute}) ({timezone.now() - start_time})\n    - {webpage.url}')

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

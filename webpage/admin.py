from django.contrib import admin
from .models import WebPage, Domain
# Register your models here.

class WebPageAdmin(admin.ModelAdmin):
    search_fields = ['title', 'url', 'description']
    list_display = ("url", "title", "time_updated", "time_last_requested", "time_discovered", "is_source")
  
class DomainAdmin(admin.ModelAdmin):
    search_fields = ['title', 'url', 'description']
    list_display = ("url", "title", "time_last_requested", "time_discovered", "is_source")
  

admin.site.register(WebPage, WebPageAdmin)

admin.site.register(Domain, DomainAdmin)
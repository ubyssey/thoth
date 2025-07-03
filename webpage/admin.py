from django.contrib import admin
from .models import WebPage, Domain, Referral
# Register your models here.

class WebPageAdmin(admin.ModelAdmin):
    search_fields = ['title', 'url', 'description']
    list_display = ("url", "title", "time_updated", "time_last_requested", "time_discovered", "is_source")
  
class DomainAdmin(admin.ModelAdmin):
    search_fields = ['title', 'url', 'description']
    list_display = ("url", "title", "time_updated", "time_last_requested", "time_discovered", "is_source")
  
class ReferralAdmin(admin.ModelAdmin):
    search_fields = ['source_webpage__url', 'destination_webpage__url']
    list_display = ("source_webpage", "destination_webpage")

admin.site.register(WebPage, WebPageAdmin)

admin.site.register(Domain, DomainAdmin)

admin.site.register(Referral, ReferralAdmin)
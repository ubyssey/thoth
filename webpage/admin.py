from django.contrib import admin
from .models import WebPage, Domain, Referral, Embeddings
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

class EmbeddingsAdmin(admin.ModelAdmin):
    search_fields = ['webpage__url', 'source_attribute']
    list_display = ('webpage', 'source_attribute')
    

admin.site.register(WebPage, WebPageAdmin)

admin.site.register(Domain, DomainAdmin)

admin.site.register(Referral, ReferralAdmin)

admin.site.register(Embeddings, EmbeddingsAdmin)
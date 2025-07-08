from django.contrib import admin
from organize_webpages.models import ThothTag, ThothTaggedItem
# Register your models here.

class ThothTagAdmin(admin.ModelAdmin):
    search_fields = ['name', 'slug']
    list_display = ("name", "slug", "children")

class TaggedObjectsAdmin(admin.ModelAdmin):
    list_display = ("tag","is_direct", "object_id")

admin.site.register(ThothTag, ThothTagAdmin)
admin.site.register(ThothTaggedItem, TaggedObjectsAdmin)


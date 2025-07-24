from django.contrib import admin
from notes.models import Note

# Register your models here.
class NoteAdmin(admin.ModelAdmin):
    search_fields = ['text']
    list_display = ('user', 'text', 'time_published')
    

admin.site.register(Note, NoteAdmin)
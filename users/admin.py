from django.contrib import admin
from users.models import ThothUser

# Register your models here.
class UserAdmin(admin.ModelAdmin):
    search_fields = ['username', 'email']
    list_display = ('username', 'email')
    

admin.site.register(ThothUser, UserAdmin)

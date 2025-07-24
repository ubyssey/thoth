from django.db import models

from users.models import ThothUser

# Create your models here.

class Note(models.Model):
    user = models.ForeignKey(ThothUser, on_delete=models.RESTRICT)
    text = models.TextField()

    time_published = models.DateTimeField(auto_now_add=True)
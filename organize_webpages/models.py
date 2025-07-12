from django.db import models

from taggit.models import TagBase, GenericTaggedItemBase
from taggit.managers import TaggableManager

# Create your models here.
class ThothTag(TagBase):
    '''
    This is a custoom Tag model so that we can add fields and methods as needed 
    '''
    is_top_level = models.BooleanField(default=False)
    parents = models.ManyToManyField('self', related_name="children", symmetrical=False, blank=True)

class ThothTaggedItem(GenericTaggedItemBase):
    tag = models.ForeignKey(
        ThothTag,
        on_delete=models.CASCADE,
        related_name="items",
    )
    is_direct = models.BooleanField(default=True)

class AbstractTaggableObject(models.Model):
    tags = TaggableManager(through=ThothTaggedItem, blank=True)
    
    class Meta():
        abstract = True
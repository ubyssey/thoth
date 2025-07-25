# Generated by Django 4.2.21 on 2025-07-07 21:59

from django.db import migrations
import taggit.managers


class Migration(migrations.Migration):

    dependencies = [
        ('organize_webpages', '0002_thothtag_is_top_level_alter_thothtaggeditem_tag'),
        ('webpage', '0008_alter_referral_destination_domain_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='domain',
            name='tags',
            field=taggit.managers.TaggableManager(help_text='A comma-separated list of tags.', through='organize_webpages.ThothTaggedItem', to='organize_webpages.ThothTag', verbose_name='Tags'),
        ),
        migrations.AddField(
            model_name='webpage',
            name='tags',
            field=taggit.managers.TaggableManager(help_text='A comma-separated list of tags.', through='organize_webpages.ThothTaggedItem', to='organize_webpages.ThothTag', verbose_name='Tags'),
        ),
    ]

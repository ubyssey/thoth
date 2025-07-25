# Generated by Django 4.2.21 on 2025-07-03 05:18

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('webpage', '0004_referral'),
    ]

    operations = [
        migrations.AddField(
            model_name='domain',
            name='crawl_page',
            field=models.URLField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='domain',
            name='crawl_page_time_last_requested',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='domain',
            name='crawl_page_type',
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterField(
            model_name='webpage',
            name='domain',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='webpages', to='webpage.domain'),
        ),
    ]

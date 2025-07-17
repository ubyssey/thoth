"""
URL configuration for thoth project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include, path

import rest_framework
from rest_framework import routers

import thoth.views as views
from webpage.views import WebPageViewSet, DomainViewSet
from organize_webpages.views import ThothTagViewSet, ThothTagNestedViewSet, add_domain
from users.views import user_login, GetUser

# Routers provide an easy way of automatically determining the URL conf.
router = routers.DefaultRouter()
router.register(r'webpages', WebPageViewSet, "Webpage")
router.register(r'domains', DomainViewSet, "Domain")
router.register(r'tags', ThothTagViewSet)
router.register(r'tags-nested', ThothTagNestedViewSet, 'tags full')

urlpatterns = [
    path("webpage/", include("webpage.urls")),
    path("admin/", admin.site.urls),

    path("domain/<int:domain_id>/", views.domain, name="domain"), 
    path("answer/", views.answer_query),
    path("", views.index, name="index"),   
    path('api-auth/', include('rest_framework.urls')),
    path("api/tags/add-domain/", add_domain),
    path("api/", include(router.urls)),
    path("login/", user_login),
    path("authed-user/", GetUser.as_view()),
]

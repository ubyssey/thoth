from django.utils import timezone

from bs4 import BeautifulSoup

from rest_framework import serializers, viewsets

from users.views import UserSerializer
from notes.models import Note

from webpage.models import WebPage
from webpage.views import WebPageWithDomainSerializer

# Create your views here.
class NoteSerializer(serializers.Serializer):
    user = UserSerializer(read_only=True)
    text = serializers.CharField()
    time_published = serializers.DateTimeField(read_only=True)
    links = serializers.SerializerMethodField()

    def create(self, validated_data):
        return Note.objects.create(text=validated_data.get('text'), user_id=self.context['request'].user.id)
    
    def get_links(self, instance):
        soup = BeautifulSoup(instance.text, "html.parser")
        links = [anchor.get("href") for anchor in soup.find_all("a")]
        print(links)
        return WebPageWithDomainSerializer(WebPage.objects.filter(url__in=links), many=True).data

# ViewSets define the view behavior.
class NotesViewSet(viewsets.ModelViewSet):
    queryset = Note.objects.all().order_by("-time_published")
    filterset_fields = ['id', 'user', 'text', 'time_published']
    search_fields = ["user", "text"]
    serializer_class = NoteSerializer

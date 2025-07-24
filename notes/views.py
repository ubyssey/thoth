from django.utils import timezone

from rest_framework import serializers, viewsets

from users.views import UserSerializer
from notes.models import Note

# Create your views here.
class NoteSerializer(serializers.Serializer):
    user = UserSerializer(read_only=True)
    text = serializers.CharField()
    time_published = serializers.DateTimeField(read_only=True)

    def create(self, validated_data):
        return Note.objects.create(text=validated_data.get('text'), user_id=self.context['request'].user.id)
    

# ViewSets define the view behavior.
class NotesViewSet(viewsets.ModelViewSet):
    queryset = Note.objects.all()
    filterset_fields = ['id', 'user', 'text', 'time_published']
    search_fields = ["user", "text"]
    serializer_class = NoteSerializer

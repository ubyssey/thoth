from rest_framework.authtoken.models import Token
from django.contrib.auth import authenticate
from rest_framework.decorators import api_view, permission_classes
from rest_framework import permissions,status, serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.exceptions import ObjectDoesNotExist

from .models import ThothUser

class UserSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = ThothUser
        fields = ['id', 'username', 'email']


@api_view(['POST'])
@permission_classes((permissions.AllowAny,))
def user_login(request):
    if request.method == 'POST':
        username = request.data.get('username')
        password = request.data.get('password')

        user = authenticate(username=username, password=password)

        if user:
            token, _ = Token.objects.get_or_create(user=user)
            return Response({'token': token.key}, status=status.HTTP_200_OK)

        print(f'{username} {password}')
        return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

class GetUser(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, format=None):
        return Response(UserSerializer(request.user).data, status=status.HTTP_200_OK)
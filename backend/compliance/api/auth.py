from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from django.db import connection
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    refresh = request.data.get('refresh')
    if not refresh:
        return Response({'error': 'Refresh token is required'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        RefreshToken(refresh).blacklist()
    except TokenError:
        return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)
    return Response({'message': 'Logged out'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    user = request.user
    return Response({
        'id': user.id,
        'username': user.username,
        'name': user.get_full_name() or user.username,
        'email': user.email,
        'role': user.role,
        'employee_id': str(user.employee_id) if user.employee_id else None,
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def health(request):
    """Public liveness check for Railway: the process is up and the database answers."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
    return Response({'ok': True})

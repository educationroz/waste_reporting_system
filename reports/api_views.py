from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from .models import Report
from .serializers import ReportSerializer, ReportStatusSerializer
from .permissions import IsRegularUser, IsAdminRole


class ReportListCreateAPIView(APIView):
    """
    GET  /api/reports/     - Any authenticated user can list all reports
    POST /api/reports/     - Regular users only (admins blocked at backend)
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsRegularUser()]
        return [IsAuthenticated()]

    def get(self, request):
        reports = Report.objects.select_related('user').all()
        serializer = ReportSerializer(reports, many=True, context={'request': request})
        return Response(serializer.data)

    def post(self, request):
        serializer = ReportSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ReportStatusUpdateAPIView(APIView):
    """
    PATCH /api/reports/{id}/status/  - Admin only
    """
    permission_classes = [IsAdminRole]

    def patch(self, request, pk):
        try:
            report = Report.objects.get(pk=pk)
        except Report.DoesNotExist:
            return Response({'error': 'Report not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = ReportStatusSerializer(report, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            full = ReportSerializer(report, context={'request': request})
            return Response(full.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ReportDeleteAPIView(APIView):
    """
    DELETE /api/reports/{id}/  - Admin only, report must be solved
    """
    permission_classes = [IsAdminRole]

    def delete(self, request, pk):
        try:
            report = Report.objects.get(pk=pk)
        except Report.DoesNotExist:
            return Response({'error': 'Report not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not report.is_solved:
            return Response(
                {'error': 'Cannot delete report. Only solved reports can be deleted.'},
                status=status.HTTP_403_FORBIDDEN, 
            )

        report.delete()
        return Response({'message': 'Report deleted successfully.'}, status=status.HTTP_204_NO_CONTENT)
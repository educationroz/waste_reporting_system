from django.urls import path
from .api_views import (
    ReportListCreateAPIView,
    ReportStatusUpdateAPIView,
    ReportDeleteAPIView,
)

urlpatterns = [
    path('reports/', ReportListCreateAPIView.as_view(), name='api_reports'),
    path('reports/<int:pk>/status/', ReportStatusUpdateAPIView.as_view(), name='api_report_status'),
    path('reports/<int:pk>/', ReportDeleteAPIView.as_view(), name='api_report_delete'),
]
from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register_view, name='register'),
    path('map/', views.map_view, name='map_view'),
    path('submit/', views.submit_report, name='submit_report'),
    path('dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('reports/<int:pk>/status/', views.update_status, name='update_status'),
    path('reports/<int:pk>/delete/', views.delete_report, name='delete_report'),
]
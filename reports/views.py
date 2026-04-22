from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_POST

from .models import Report, User
from .forms import RegisterForm, ReportForm


def home(request):
    if not request.user.is_authenticated:
        return redirect('login')
    if request.user.is_admin_role():
        return redirect('admin_dashboard')
    return redirect('map_view')


def register_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Account created successfully!")
            return redirect('map_view')
    else:
        form = RegisterForm()
    return render(request, 'registration/register.html', {'form': form})


@login_required
def map_view(request):
    """Public map view for all authenticated users."""
    reports = Report.objects.select_related('user').all()
    return render(request, 'reports/map.html', {'reports': reports})


@login_required
def submit_report(request):
    """Only regular users can submit reports."""
    if request.user.is_admin_role():
        return HttpResponseForbidden("Admin accounts cannot submit reports.")

    if request.method == 'POST':
        form = ReportForm(request.POST, request.FILES)
        if form.is_valid():
            report = form.save(commit=False)
            report.user = request.user
            report.save()
            messages.success(request, "Report submitted successfully!")
            return redirect('map_view')
    else:
        form = ReportForm()
    return render(request, 'reports/submit_report.html', {'form': form})


@login_required
def admin_dashboard(request):
    """Admin-only dashboard."""
    if not request.user.is_admin_role():
        return HttpResponseForbidden("Only admins can access this page.")

    status_filter = request.GET.get('status', '')
    reports = Report.objects.select_related('user').all()
    if status_filter:
        reports = reports.filter(status=status_filter)

    stats = {
        'total': Report.objects.count(),
        'pending': Report.objects.filter(status='pending').count(),
        'in_progress': Report.objects.filter(status='in_progress').count(),
        'solved': Report.objects.filter(status='solved').count(),
    }
    return render(request, 'reports/admin_dashboard.html', {
        'reports': reports,
        'stats': stats,
        'status_filter': status_filter,
        'status_choices': Report.STATUS_CHOICES,
    })


@login_required
@require_POST
def update_status(request, pk):
    """Admin updates report status."""
    if not request.user.is_admin_role():
        return HttpResponseForbidden("Only admins can update report status.")

    report = get_object_or_404(Report, pk=pk)
    new_status = request.POST.get('status')
    valid = [c[0] for c in Report.STATUS_CHOICES]
    if new_status in valid:
        report.status = new_status
        report.save()
        messages.success(request, f"Report status updated to '{new_status}'.")
    else:
        messages.error(request, "Invalid status value.")

    return redirect('admin_dashboard')


@login_required
@require_POST
def delete_report(request, pk):
    """Admin deletes only solved reports."""
    if not request.user.is_admin_role():
        return HttpResponseForbidden("Only admins can delete reports.")

    report = get_object_or_404(Report, pk=pk)
    if not report.is_solved:
        messages.error(request, "Cannot delete: report must be marked as 'solved' first.")
        return redirect('admin_dashboard')

    report.delete()
    messages.success(request, "Report deleted successfully.")
    return redirect('admin_dashboard')
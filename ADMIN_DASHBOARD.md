# Custom Admin Dashboard - Setup and Usage Guide

## Overview

This document describes the custom admin dashboard implementation for the Waste Management System. The dashboard provides comprehensive admin controls with role-based access, activity logging, and system configuration.

## Architecture

### Components

1. **Admin Views** (`web_app/views.py`)
   - `AdminDashboardView` - Main admin dashboard with statistics and quick actions
   - `AdminUsersManagementView` - Manage admin users
   - `AdminLogsView` - View admin activity logs
   - `AdminSettingsView` - System configuration and settings

2. **Models** (`api_app/models.py`)
   - `AdminLog` - Tracks all admin actions for audit trail
   - `SystemSettings` - Stores system-wide configuration

3. **API Endpoints** (`api_app/views.py`)
   - `AdminLogViewSet` - Read-only admin logs (admin-only)
   - `SystemSettingsViewSet` - CRUD operations for system settings (admin-only)

4. **Templates** (`templates/web_app/`)
   - `admin_dashboard.html` - Main admin dashboard
   - `admin_users.html` - Admin user management
   - `admin_logs.html` - Activity logs viewer
   - `admin_settings.html` - System settings configuration

## Features

### 1. Admin Dashboard (`/admin-dashboard/`)
- **Statistics Overview**
  - Total requests (clickable to filter view)
  - Pending, assigned, in-progress, completed requests
  - Overdue requests count
  - Active/total drivers and vehicles
  - System status indicators

- **System Alerts**
  - Overdue requests warning
  - Multiple pending requests alert
  - No available drivers alert
  - No available vehicles alert

- **Quick Actions**
  - Create new waste request
  - Manage drivers, vehicles, schedules
  - View all requests
  - Admin user management
  - Activity logs
  - System settings

### 2. Admin Users Management (`/management/admin-users/`)
- **View All Admins**
  - List all admin users with status
  - Filter by active/inactive
  - View admin details (username, email, phone)

- **Create New Admin User**
  - Add new admin accounts
  - Set username, email, password
  - Assign permissions (Users, Requests, Drivers, Settings)

- **Delete Admin Users**
  - Remove admin accounts from the system
  - Confirmation before deletion

### 3. Activity Logs (`/management/activity-logs/`)
- **Audit Trail**
  - Track all admin actions
  - View action type (Create, Update, Delete, Status Change, etc.)
  - See which admin performed the action
  - IP address tracking
  - Timestamp of action

- **Filtering & Search**
  - Filter by action type
  - Filter by admin user
  - Paginated view (50 items per page)

- **Change Details**
  - View before/after changes
  - JSON format for detailed analysis

### 4. System Settings (`/management/settings/`)
- **General Settings**
  - System name
  - Default timezone
  - Max upload size
  - Session timeout
  - Maintenance mode toggle

- **Email Configuration**
  - SMTP server setup
  - Port configuration
  - TLS encryption
  - Email testing

- **Notification Preferences**
  - Toggle notifications for different events
  - New waste requests
  - Status changes
  - Driver offline events
  - Overdue requests

- **Backup & Restore**
  - Create database backups
  - Restore from backup files
  - View backup history

## API Endpoints

### Admin Logs API
```
GET    /api/admin-logs/              - List all admin logs
GET    /api/admin-logs/?action=...   - Filter by action
GET    /api/admin-logs/?search=...   - Search logs
```

### System Settings API
```
GET    /api/system-settings/         - List all settings
POST   /api/system-settings/         - Create new setting
GET    /api/system-settings/{key}/   - Get specific setting
PUT    /api/system-settings/{key}/   - Update setting
DELETE /api/system-settings/{key}/   - Delete setting
```

## Models

### AdminLog
```python
class AdminLog(models.Model):
    admin_user      - FK to User (admin who performed action)
    action          - Choice field (create, update, delete, assign, status_change, login, etc.)
    content_type    - String identifying the object type
    object_id       - ID of the affected object
    object_description - Human-readable description
    changes         - JSON field storing before/after values
    ip_address      - IP address of the action
    user_agent      - Browser/client info
    created_at      - Timestamp of action
```

### SystemSettings
```python
class SystemSettings(models.Model):
    key            - Unique identifier for the setting
    value          - JSON field storing the setting value
    description    - Human-readable description
    is_sensitive   - Boolean to hide sensitive values in logs
    updated_by     - FK to User (admin who updated)
    updated_at     - Last update timestamp
```

## Permissions

### Access Control
- **Admin Dashboard**: Requires `role='admin'` + `LoginRequiredMixin`
- **Admin Logs**: Requires `role='admin'` + `IsAdminUser` permission
- **System Settings**: Requires `role='admin'` + `IsAdminUser` permission

### Permission Classes
- `IsAdminUser` - Only allow users with role='admin'
- `IsAdminOrReadOnly` - Admins full access, others read-only
- `IsOwnerOrAdmin` - Owner or admin can access object

## Usage Examples

### Creating an Admin User via API
```bash
POST /auth/create-admin/
{
    "username": "admin1",
    "email": "admin1@example.com",
    "password": "secure_password",
    "role": "admin"
}
```

### Logging Admin Actions
```python
from api_app.models import AdminLog
from api_app.utils import log_admin_action

# Log an admin action
log_admin_action(
    admin_user=request.user,
    action='create',
    content_type='Driver',
    object_id=driver.id,
    object_description=f"Driver: {driver.user.username}",
    ip_address=get_client_ip(request),
    changes={'field': 'value'}
)
```

### Retrieving System Settings
```python
from api_app.models import SystemSettings

# Get a setting
setting = SystemSettings.objects.get(key='max_file_size')
value = setting.value  # Returns JSON value

# Update a setting
setting.value = {'size': 100}
setting.save()
```

## Navigation

The admin dashboard is integrated into the main navigation:
- **Dashboard** - Main admin dashboard
- **Requests** - Manage all waste requests
- **Drivers** - Manage drivers
- **Vehicles** - Manage vehicles
- **Schedules** - Manage schedules
- **Admins** - Manage admin users
- **Logs** - View activity logs
- **Settings** - System configuration

## Security Features

1. **Role-Based Access Control**
   - Only users with role='admin' can access admin features
   - LoginRequiredMixin enforces authentication

2. **Audit Trail**
   - All admin actions are logged with timestamp, IP, and user agent
   - Changes are stored in JSON format for analysis

3. **Sensitive Data Protection**
   - Settings can be marked as sensitive to hide values in logs
   - IP addresses and user agents are tracked

4. **Activity Monitoring**
   - Track who did what and when
   - Filter and search logs for security analysis
   - Identify suspicious activities

## Database Migrations

The system includes a migration file for the new models:
- `api_app/migrations/0005_systemsettings_adminlog.py`

To apply migrations:
```bash
python manage.py migrate
```

## Future Enhancements

1. **Advanced Reporting**
   - Generate admin activity reports
   - Export logs to CSV/PDF

2. **Real-time Alerts**
   - Real-time admin activity notifications
   - Critical action alerts

3. **Two-Factor Authentication**
   - MFA for admin accounts
   - Increased security for sensitive operations

4. **Role-Based Permissions**
   - Fine-grained permission control
   - Custom admin roles

5. **Automation**
   - Automated backup scheduling
   - Email notifications for system events

## Troubleshooting

### Admin dashboard not showing
- Check that user has role='admin'
- Verify LoginRequiredMixin is working
- Check browser console for errors

### Activity logs not recording
- Verify AdminLog model is created
- Check that migrations are applied
- Ensure log_admin_action() is being called

### Settings not persisting
- Check database connection
- Verify SystemSettings table exists
- Check user permissions

## Support

For issues or questions about the admin dashboard, please refer to:
- Django documentation: https://docs.djangoproject.com/
- Django REST Framework: https://www.django-rest-framework.org/
- Project README: ../README.md

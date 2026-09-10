"""
Management command to generate routes from schedules for the next 7 days.
Run nightly via cron: 0 2 * * * /path/to/python manage.py generate_routes
"""
from datetime import timedelta, date
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from api_app.models import Schedule, Route, WasteRequest, ZONE_CHOICES
from api_app.route_optimizer import DepotLocationError, generate_optimal_route


class Command(BaseCommand):
    help = 'Generate waste collection routes from active schedules for the next 7 days'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Number of days ahead to generate routes (default: 7)'
        )
        parser.add_argument(
            '--zone',
            type=str,
            help='Generate routes only for specific zone'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be generated without creating routes'
        )
        parser.add_argument(
            '--max-requests',
            type=int,
            default=20,
            help='Maximum requests per route (default: 20)'
        )

    def handle(self, *args, **options):
        days_ahead = options['days']
        zone_filter = options['zone']
        dry_run = options['dry_run']
        max_requests = options['max_requests']

        today = timezone.now().date()
        end_date = today + timedelta(days=days_ahead)

        self.stdout.write(f'Generating routes from {today} to {end_date}')

        active_schedules = Schedule.objects.filter(
            is_active=True,
            driver__isnull=False,
        ).select_related('driver__user', 'vehicle')

        if zone_filter:
            active_schedules = active_schedules.filter(zone_name=zone_filter)

        if not active_schedules.exists():
            self.stdout.write(self.style.WARNING('No active schedules with drivers found'))
            return

        created_count = 0
        skipped_count = 0
        errors = []

        for schedule in active_schedules:
            run_dates = self.get_run_dates(schedule, today, end_date)

            for planned_date in run_dates:
                # Check if route already exists
                if Route.objects.filter(
                    driver=schedule.driver,
                    planned_date=planned_date,
                    status='planned'
                ).exists():
                    skipped_count += 1
                    continue

                # Get pending requests in this zone
                zone_key = schedule.zone_name.lower().replace(' ', '_')
                if zone_key not in dict(ZONE_CHOICES):
                    zone_key = schedule.zone_name

                pending_requests = list(WasteRequest.objects.filter(
                    zone=zone_key,
                    status='pending',
                    driver__isnull=True,
                    is_deleted=False,
                ).filter(
                    Q(latitude__isnull=False, longitude__isnull=False) |
                    Q(photo_latitude__isnull=False, photo_longitude__isnull=False)
                ).order_by('created_at')[:max_requests])

                if not pending_requests:
                    self.stdout.write(
                        f'  No pending requests for {schedule.zone_name} on {planned_date}'
                    )
                    continue

                request_ids = [wr.id for wr in pending_requests]

                try:
                    route_data = generate_optimal_route(schedule.driver, request_ids, [])
                except DepotLocationError as exc:
                    errors.append(f'{schedule.zone_name} {planned_date}: {exc}')
                    continue
                if 'error' in route_data:
                    errors.append(f'{schedule.zone_name} {planned_date}: {route_data["error"]}')
                    continue

                if dry_run:
                    self.stdout.write(
                        f'  [DRY RUN] Would create route for {schedule.zone_name} '
                        f'on {planned_date}: {route_data["total_stops"]} stops, '
                        f'{route_data["total_distance_km"]:.1f} km'
                    )
                    created_count += 1
                    continue

                # Create route
                try:
                    with transaction.atomic():
                        route = Route.objects.create(
                            driver=schedule.driver,
                            vehicle=schedule.vehicle or schedule.driver.vehicle,
                            planned_date=planned_date,
                            status='planned',
                            total_distance_km=route_data['total_distance_km'],
                        )
                        route.waste_requests.set(request_ids)
                        WasteRequest.objects.filter(id__in=request_ids).update(
                            driver=schedule.driver, status='assigned'
                        )
                        created_count += 1

                        self.stdout.write(
                            self.style.SUCCESS(
                                f'  Created route #{route.id} for {schedule.zone_name} '
                                f'on {planned_date}: {route_data["total_stops"]} stops, '
                                f'{route_data["total_distance_km"]:.1f} km'
                            )
                        )
                except Exception as exc:
                    errors.append(f'{schedule.zone_name} {planned_date}: {exc}')
                    continue

        # Summary
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Routes created: {created_count}'))
        self.stdout.write(f'Routes skipped (already exist): {skipped_count}')
        if errors:
            self.stdout.write(self.style.ERROR(f'Errors: {len(errors)}'))
            for err in errors:
                self.stdout.write(f'  - {err}')

    def get_run_dates(self, schedule, today, end_date):
        """Determine which dates a schedule runs on within the date range."""
        run_dates = []
        current = today

        while current <= end_date:
            if schedule.frequency == 'daily':
                run_dates.append(current)
            elif schedule.frequency == 'weekly' and schedule.day_of_week is not None:
                if current.weekday() == schedule.day_of_week:
                    run_dates.append(current)
            elif schedule.frequency == 'biweekly' and schedule.day_of_week is not None:
                weeks_diff = (current - today).days // 7
                if weeks_diff % 2 == 0 and current.weekday() == schedule.day_of_week:
                    run_dates.append(current)
            elif schedule.frequency == 'monthly' and schedule.day_of_week is not None:
                if current.weekday() == schedule.day_of_week and current.day <= 7:
                    run_dates.append(current)
            current += timedelta(days=1)

        return run_dates
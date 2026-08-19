"""
Compile locale/<lang>/LC_MESSAGES/*.po into the binary .mo files Django reads.

WHY THIS EXISTS
    Django's built-in `compilemessages` shells out to GNU gettext's `msgfmt`
    binary. On Windows (and on slim Linux/Docker images) gettext often isn't
    installed, and `compilemessages` fails with
    "Can't find msgfmt. Make sure you have GNU gettext tools installed".
    This command does the same job in pure Python via `polib`, so translations
    can be rebuilt anywhere Python runs.

USAGE
    python manage.py compilemessages_py

    Run it after ANY edit to a .po file. Django loads the compiled .mo, not the
    .po, so an un-compiled edit silently has no effect on the site.

    Restart the server afterwards: Django caches translation catalogs in
    memory for the life of the process.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Compile .po files into .mo files using polib (no gettext binaries needed).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--locale', '-l', default=None,
            help='Only compile this locale (e.g. "ne"). Default: all locales.',
        )

    def handle(self, *args, **options):
        try:
            import polib
        except ImportError:
            raise CommandError(
                'polib is required. Install it with:  pip install polib'
            )

        locale_paths = [Path(p) for p in getattr(settings, 'LOCALE_PATHS', [])]
        if not locale_paths:
            raise CommandError('settings.LOCALE_PATHS is empty — nothing to compile.')

        wanted = options['locale']
        compiled = 0

        for base in locale_paths:
            if not base.is_dir():
                self.stdout.write(self.style.WARNING(f'skipping missing dir: {base}'))
                continue

            for po_path in sorted(base.glob('*/LC_MESSAGES/*.po')):
                lang = po_path.parent.parent.name
                if wanted and lang != wanted:
                    continue

                po = polib.pofile(str(po_path))
                mo_path = po_path.with_suffix('.mo')
                po.save_as_mofile(str(mo_path))

                translated = len(po.translated_entries())
                total = len([e for e in po if not e.obsolete])
                fuzzy = len(po.fuzzy_entries())
                compiled += 1

                msg = f'{lang}: {translated}/{total} translated -> {mo_path}'
                if fuzzy:
                    msg += f' ({fuzzy} fuzzy)'
                self.stdout.write(self.style.SUCCESS(msg))

        if not compiled:
            raise CommandError('No .po files found to compile.')

        self.stdout.write(self.style.SUCCESS(
            f'\nDone: {compiled} catalog(s) compiled. '
            'Restart the server for the changes to take effect.'
        ))

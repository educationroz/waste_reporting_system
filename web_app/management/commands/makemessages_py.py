"""
Extract translatable strings into locale/<lang>/LC_MESSAGES/django.po.

WHY THIS EXISTS
    Django's built-in `makemessages` needs GNU gettext's `xgettext` binary,
    which usually isn't present on Windows or on slim Docker images. This is a
    pure-Python stand-in (only `polib` required) covering the patterns this
    project actually uses:

        templates : {% trans "..." %}, {% blocktrans %}...{% endblocktrans %}
        inline JS : gettext('...')      (served by the /jsi18n/ catalog)
        python    : _('...'), gettext('...'), gettext_lazy('...')

    Existing translations are PRESERVED — a msgid that already has a msgstr
    keeps it. Strings no longer found in the code are dropped, and new ones are
    added with an empty msgstr ready to be filled in.

USAGE
    python manage.py makemessages_py            # updates every locale
    python manage.py makemessages_py -l ne      # just Nepali

    Then translate the empty msgstr entries in the .po file and run:
    python manage.py compilemessages_py
"""

import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# {% trans "x" %} / {% translate 'x' %}  (optionally "... as var")
TRANS_RE = re.compile(
    r'\{%\s*trans(?:late)?\s+(["\'])(.*?)\1\s*(?:as\s+\w+\s*)?%\}', re.DOTALL)
# {% blocktrans %}x{% endblocktrans %}
BLOCK_RE = re.compile(
    r'\{%\s*blocktrans(?:late)?[^%]*%\}(.*?)\{%\s*endblocktrans(?:late)?\s*%\}', re.DOTALL)
# gettext('x') in inline <script> blocks and .js files
JS_RE = re.compile(r'\bgettext\(\s*(["\'])((?:[^"\'\\]|\\.)*?)\1\s*\)')
# _('x') / gettext('x') / gettext_lazy('x') in Python
PY_RE = re.compile(
    r'\b(?:gettext_lazy|gettext|ugettext|_)\(\s*(["\'])((?:[^"\'\\]|\\.)*?)\1\s*\)', re.DOTALL)

SKIP_DIRS = {'.venv', 'venv', 'env', 'node_modules', '__pycache__',
             'migrations', '.git', 'staticfiles', 'media', 'locale'}


def js_unescape(s):
    """JS literal body -> the runtime string gettext() actually receives."""
    return (s.replace('\\\\', '\x00')
             .replace("\\'", "'")
             .replace('\\"', '"')
             .replace('\\n', '\n')
             .replace('\\t', '\t')
             .replace('\x00', '\\'))


class Command(BaseCommand):
    help = 'Extract translatable strings into .po files using polib (no gettext binaries needed).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--locale', '-l', default=None,
            help='Only update this locale (e.g. "ne"). Default: every locale that already exists.',
        )

    # ── collection ────────────────────────────────────────────────────
    def collect(self, root):
        found = {}

        def add(msgid, path, text, pos):
            msgid = re.sub(r'\s+', ' ', msgid).strip()
            if not msgid:
                return
            line = text.count('\n', 0, pos) + 1
            rel = path.relative_to(root).as_posix()
            found.setdefault(msgid, set()).add((rel, str(line)))

        def walk(pattern):
            for p in root.rglob(pattern):
                if any(part in SKIP_DIRS for part in p.parts):
                    continue
                yield p

        for p in walk('*.html'):
            t = p.read_text(encoding='utf-8', errors='ignore')
            for m in TRANS_RE.finditer(t):
                add(m.group(2), p, t, m.start())
            for m in BLOCK_RE.finditer(t):
                add(m.group(1), p, t, m.start())
            for m in JS_RE.finditer(t):
                add(js_unescape(m.group(2)), p, t, m.start())

        for p in walk('*.py'):
            if p.name.startswith('_') or p.stem in {
                    'makemessages_py', 'compilemessages_py'}:
                continue
            t = p.read_text(encoding='utf-8', errors='ignore')
            for m in PY_RE.finditer(t):
                add(m.group(2), p, t, m.start())

        for p in walk('*.js'):
            t = p.read_text(encoding='utf-8', errors='ignore')
            for m in JS_RE.finditer(t):
                add(js_unescape(m.group(2)), p, t, m.start())

        return found

    # ── main ──────────────────────────────────────────────────────────
    def handle(self, *args, **options):
        try:
            import polib
        except ImportError:
            raise CommandError('polib is required. Install it with:  pip install polib')

        root = Path(settings.BASE_DIR)
        locale_paths = [Path(p) for p in getattr(settings, 'LOCALE_PATHS', [])]
        if not locale_paths:
            raise CommandError('settings.LOCALE_PATHS is empty.')
        base = locale_paths[0]

        wanted = options['locale']
        if wanted:
            languages = [wanted]
        else:
            languages = sorted(
                d.name for d in base.glob('*') if (d / 'LC_MESSAGES').is_dir()
            ) or [code for code, _ in getattr(settings, 'LANGUAGES', [])
                  if code != settings.LANGUAGE_CODE.split('-')[0]]

        found = self.collect(root)
        self.stdout.write(f'Found {len(found)} translatable string(s) in the codebase.')

        for lang in languages:
            po_path = base / lang / 'LC_MESSAGES' / 'django.po'
            po_path.parent.mkdir(parents=True, exist_ok=True)

            if po_path.exists():
                old = polib.pofile(str(po_path))
                metadata = old.metadata
                existing = {e.msgid: e for e in old}
            else:
                metadata = {
                    'Project-Id-Version': 'waste_reporting_system 1.0',
                    'Report-Msgid-Bugs-To': '',
                    'MIME-Version': '1.0',
                    'Content-Type': 'text/plain; charset=UTF-8',
                    'Content-Transfer-Encoding': '8bit',
                    'Language': lang,
                    'Plural-Forms': 'nplurals=2; plural=(n != 1);',
                }
                existing = {}

            po = polib.POFile()
            po.metadata = metadata

            kept = new = 0
            for msgid in sorted(found):
                occurrences = sorted(found[msgid])
                prev = existing.get(msgid)
                if prev is not None and prev.msgstr:
                    entry = polib.POEntry(
                        msgid=msgid, msgstr=prev.msgstr,
                        occurrences=occurrences, flags=prev.flags,
                    )
                    kept += 1
                else:
                    entry = polib.POEntry(
                        msgid=msgid, msgstr='', occurrences=occurrences)
                    new += 1
                po.append(entry)

            removed = len([m for m in existing if m and m not in found])
            po.save(str(po_path))

            self.stdout.write(self.style.SUCCESS(
                f'{lang}: {len(po)} msgids  ({kept} existing kept, '
                f'{new} untranslated, {removed} obsolete removed)  -> {po_path}'
            ))

        self.stdout.write(
            '\nNext: fill in the empty msgstr entries, then run:\n'
            '  python manage.py compilemessages_py'
        )

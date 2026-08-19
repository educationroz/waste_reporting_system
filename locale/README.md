# Translations (English → नेपाली)

The whole UI — admin, driver and citizen dashboards — is translated into Nepali.
Switching the language dropdown in the navbar re-renders every page server-side
in the chosen language.

```
locale/
└── ne/
    └── LC_MESSAGES/
        ├── django.po   ← the translations (edit this)
        └── django.mo   ← compiled binary (generated; Django reads THIS)
```

---

## How it works

| Piece | Where | Notes |
|---|---|---|
| Language list | `waste_system/settings.py` → `LANGUAGES` | `en` + `ne` |
| Language switcher | `templates/web_app/base.html` | POSTs to Django's `set_language` |
| Request → language | `LocaleMiddleware` | session → cookie → `Accept-Language` |
| Template strings | `{% trans "..." %}` / `{% blocktrans %}` | needs `{% load i18n %}` in the file |
| Python strings | `gettext as _` | e.g. dashboard alerts in `web_app/views.py` |
| **JavaScript strings** | `gettext('...')` | served by `/jsi18n/` (`JavaScriptCatalog`) |
| Model labels | `gettext_lazy` in `choices` | `get_status_display` etc. translate automatically |

Dropdown labels use `name_local`, so each language is shown in its own script
("English", "नेपाली") — someone who switches by accident can always switch back.

---

## Changing or adding a translation

1. **Edit** `locale/ne/LC_MESSAGES/django.po` — find the `msgid` and fill in `msgstr`:

   ```po
   msgid "Total Requests"
   msgstr "कुल अनुरोधहरू"
   ```

2. **Compile** (this is the step people forget — Django reads the `.mo`, not the `.po`):

   ```bash
   python manage.py compilemessages_py
   ```

3. **Restart the server.** Translation catalogs are cached in memory per process.

## After adding NEW text to a template / view / script

Wrap it first…

```django
<h2>{% trans "My new heading" %}</h2>
```
```python
messages.success(request, _('Saved!'))
```
```javascript
showToast(gettext('Saved!'), 'success');
```

…then re-scan, translate the new empty entries, and compile:

```bash
python manage.py makemessages_py -l ne   # adds new msgids, keeps existing translations
# ...fill in the new msgstr values in django.po...
python manage.py compilemessages_py
```

---

## Why `*_py` commands instead of Django's built-ins?

Django's `makemessages` / `compilemessages` shell out to the **GNU gettext**
binaries (`xgettext`, `msgfmt`), which aren't installed on most Windows machines
or slim Docker images, and fail with:

> Can't find msgfmt. Make sure you have GNU gettext tools installed.

`makemessages_py` and `compilemessages_py` (in `web_app/management/commands/`)
do the same job in pure Python using `polib`, so translations can be rebuilt
anywhere Python runs. The stock Django commands still work fine if you do have
gettext installed.

---

## Gotchas worth knowing

- **A `msgid` starting with `%`** never matches. Django escapes a literal `%` to
  `%%` for its interpolation machinery, so `{% trans "% confidence" %}` stays
  English. Keep the `%` outside the tag: `{{ value }}% {% trans "confidence" %}`.
- **HTML entities belong outside the tag.** `{% trans "&copy; Safha Sahar" %}`
  renders the escaped text `&amp;copy;`. Write `&copy; {% trans "Safha Sahar" %}`.
- **Don't use `strftime('%B')` for month names** — it reads the OS C locale and
  ignores the active language. Pass the datetime to the template and format it
  with `{{ value|date:"F Y" }}`, which is language-aware.
- **`{# ... #}` inside an HTML tag's attribute area** can end up in the output;
  use `{% comment %}` blocks for multi-line notes.
- **The `.mo` file is committed on purpose** so the app runs correctly straight
  from a clone, without anyone needing gettext.

## Deliberately left in English

Brand and protocol tokens: `SafhaSahar`, `RA Innovations`, `SMTP`, `TLS`, `PDF`,
`CSV`, timezone codes (`UTC`, `EST`, `CST`, `PST`) and the sample e-mail
placeholders (`you@example.com`, `smtp.gmail.com`).

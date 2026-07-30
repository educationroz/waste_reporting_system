"""
Standalone Gmail SMTP test — completely independent of Django.
Run with: py test_email.py

SECURITY NOTICE (FIXED 2026-07-29):
  Never hardcode credentials in source files. This script now reads its
  values from OS environment variables or (optionally) from a local
  python-decouple .env file that is listed in .gitignore.

Setup (one time):
  1. Revoke any App Passwords previously committed to the repository
     at https://myaccount.google.com/apppasswords
  2. Create a NEW App Password for this project.
  3. Export the values BEFORE running the script:

        PowerShell:
          $env:GMAIL_USER="your-address@gmail.com"
          $env:GMAIL_APP_PASSWORD="abcdabcdabcdabcd"
          py test_email.py

        Bash:
          export GMAIL_USER="your-address@gmail.com"
          export GMAIL_APP_PASSWORD="abcdabcdabcdabcd"
          python3 test_email.py
"""

import os
import smtplib
from email.mime.text import MIMEText

# --- load from environment (NOT from hardcoded strings) -------------------
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

# Try python-decouple if available and env vars are not set, so this works
# alongside the Django .env file.
if not GMAIL_USER or not GMAIL_APP_PASSWORD:
    try:
        from decouple import config  # type: ignore
        GMAIL_USER = GMAIL_USER or config("GMAIL_USER", default="")
        GMAIL_APP_PASSWORD = GMAIL_APP_PASSWORD or config("EMAIL_HOST_PASSWORD", default="")
    except ImportError:
        pass

TO_ADDRESS = GMAIL_USER  # send test to self by default


def _fail_and_exit(msg: str) -> None:
    print("ERROR: " + msg)
    print(
        "Set the GMAIL_USER / GMAIL_APP_PASSWORD environment variables "
        "before running this script. See the module docstring for examples."
    )
    raise SystemExit(1)


def main() -> None:
    """Run the SMTP check.

    Everything lives in here (rather than at module import time) because
    Django's test runner auto-discovers any top-level ``test*.py`` module.
    When the credential checks ran at import time this file raised
    ``SystemExit(1)`` during discovery and broke the whole ``manage.py test``
    run. Keeping the work behind ``main()`` / ``__main__`` makes the module
    safe to import while still working as a standalone script.
    """
    if not GMAIL_USER:
        _fail_and_exit("GMAIL_USER is not set.")
    if not GMAIL_APP_PASSWORD:
        _fail_and_exit("GMAIL_APP_PASSWORD is not set.")

    msg = MIMEText("This is a standalone SMTP test, not from Django.")
    msg["Subject"] = "SMTP test"
    msg["From"] = GMAIL_USER
    msg["To"] = TO_ADDRESS

    try:
        print("Connecting to smtp.gmail.com:587 ...")
        server = smtplib.SMTP("smtp.gmail.com", 587)
        # Disable debug output in anything that looks like production; the
        # previous level 1 printed the full SMTP conversation including
        # credentials, which would leak into CI logs / shared terminal logs.
        server.set_debuglevel(0)
        server.starttls()
        print(f"Attempting login as: {GMAIL_USER!r}")
        print(f"Password length: {len(GMAIL_APP_PASSWORD)}")
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        print("LOGIN SUCCEEDED")
        server.sendmail(GMAIL_USER, [TO_ADDRESS], msg.as_string())
        print("EMAIL SENT SUCCESSFULLY")
        server.quit()
    except Exception as e:
        # NEVER print the raw exception with credentials — show type + message only.
        print(f"FAILED: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()

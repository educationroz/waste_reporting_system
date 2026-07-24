"""
Standalone Gmail SMTP test — completely independent of Django.
Run with: py test_email.py

Edit the two values below with your real Gmail address and App Password
(the 16-character one, no spaces) before running.
"""

import smtplib
from email.mime.text import MIMEText

GMAIL_USER = "roztmagar@gmail.com"
GMAIL_APP_PASSWORD = "lcevykhgmsbyynbr"       # <-- your 16-char App Password, no spaces

TO_ADDRESS = GMAIL_USER  # sending a test email to yourself

msg = MIMEText("This is a standalone SMTP test, not from Django.")
msg["Subject"] = "SMTP test"
msg["From"] = GMAIL_USER
msg["To"] = TO_ADDRESS

try:
    print("Connecting to smtp.gmail.com:587 ...")
    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.set_debuglevel(1)  # prints the full SMTP conversation
    server.starttls()
    print(f"Attempting login as: {GMAIL_USER!r}")
    print(f"Password length: {len(GMAIL_APP_PASSWORD)}")
    server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    print("LOGIN SUCCEEDED")
    server.sendmail(GMAIL_USER, [TO_ADDRESS], msg.as_string())
    print("EMAIL SENT SUCCESSFULLY")
    server.quit()
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
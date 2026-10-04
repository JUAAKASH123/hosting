import os
import html
import ssl
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT_STARTTLS = 587
SMTP_PORT_SSL = 465

# 10s was too tight: Gmail can take longer than that to answer MAIL FROM,
# which surfaced as "Connection unexpectedly closed: The read operation
# timed out". 30s is still bounded, so a hung connection can't tie up the
# shared threadpool indefinitely.
SMTP_TIMEOUT_SECONDS = int(os.environ.get("SMTP_TIMEOUT_SECONDS", "10"))
SMTP_ATTEMPTS = 3  # attempts 1-2 use 587/STARTTLS, attempt 3 falls back to 465/SSL

# Credentials come from environment / .env (never hardcode).
# VIRTUFIT_APP_PASSWORD must be a Gmail App Password (16 chars), not your login password.
EMAIL = os.environ.get("VIRTUFIT_EMAIL")
PASSWORD = os.environ.get("VIRTUFIT_APP_PASSWORD")

LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "image", "logo_icon_v2.png")

# Read the logo once instead of on every login. Keep this file small
# (ideally under ~50 KB) — large inline images slow SMTP delivery.
_logo_bytes = None
try:
    with open(LOGO_PATH, "rb") as _f:
        _logo_bytes = _f.read()
    if len(_logo_bytes) > 200 * 1024:
        print(f"⚠️  Logo is {len(_logo_bytes) // 1024} KB — consider resizing to <50 KB to speed up email delivery.")
except FileNotFoundError:
    print(f"⚠️  Logo not found at {LOGO_PATH} — emails will be sent without the inline logo.")


def assert_email_configured():
    """Call once at startup (after firebase_admin.initialize_app) so a bad deploy fails fast."""
    if not EMAIL or not PASSWORD:
        raise RuntimeError(
            "Missing credentials. Set VIRTUFIT_EMAIL and VIRTUFIT_APP_PASSWORD "
            "as environment variables before starting the app."
        )


def _build_message(name, user_email):
    # name is user-controlled (displayName) — escape it for the HTML part only.
    safe_name = html.escape(name)

    msg = MIMEMultipart("related")
    msg["Subject"] = "Successful Login - VirtuFit"
    msg["From"] = f"VirtuFit <{EMAIL}>"
    msg["To"] = user_email

    alt = MIMEMultipart("alternative")
    msg.attach(alt)

    plain_text = f"""Hi {name},

We noticed a successful sign in to your VirtuFit account.
You're now ready to explore our AI-powered virtual dressing room.

If this wasn't you, please change your password immediately.

Visit VirtuFit: https://virtufit.in

- VirtuFit Team
"""
    alt.attach(MIMEText(plain_text, "plain"))

    body = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VirtuFit Login Notification</title>
</head>

<body style="margin:0;padding:0;background-color:#f3f0fb;font-family:'Segoe UI',Helvetica,Arial,sans-serif;">

<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f3f0fb;padding:32px 16px;">
<tr>
<td align="center">

<table role="presentation" width="600" cellpadding="0" cellspacing="0"
style="max-width:600px;width:100%;background:#ffffff;border-radius:20px;overflow:hidden;
box-shadow:0 10px 40px rgba(91,33,255,0.12);">

<!-- Header with gradient + logo -->
<tr>
<td align="center"
style="background:linear-gradient(135deg,#EC1A9E 0%,#9333EA 55%,#5B21FF 100%);
padding:36px 24px 28px 24px;">

<img src="cid:virtufit_logo" alt="VirtuFit" width="90"
style="display:block;margin:0 auto 14px auto;border:0;outline:none;text-decoration:none;" />

<h1 style="margin:0 0 6px 0;color:#ffffff;font-size:28px;font-weight:800;letter-spacing:1px;">
VirtuFit
</h1>

<p style="margin:0;color:#F3E8FF;font-size:12px;letter-spacing:3px;text-transform:uppercase;">
Style at Your Fingertips
</p>

</td>
</tr>

<!-- Status strip -->
<tr>
<td style="background:#1c1c1c;padding:14px 24px;" align="center">
<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#34D399;margin-right:8px;vertical-align:middle;"></span>
<span style="color:#ffffff;font-size:13px;letter-spacing:0.5px;vertical-align:middle;">
Login Successful
</span>
</td>
</tr>

<!-- Content -->
<tr>
<td style="padding:40px 40px 24px 40px;">

<h2 style="color:#1a1a1a;font-size:24px;margin:0 0 16px 0;font-weight:700;">
Hi {safe_name},
</h2>

<p style="font-size:15px;color:#555555;line-height:1.7;margin:0 0 16px 0;">
We noticed a successful sign in to your <strong style="color:#1a1a1a;">VirtuFit</strong> account.
You're all set to explore your AI-powered virtual dressing room.
</p>

<p style="font-size:15px;color:#555555;line-height:1.7;margin:0 0 28px 0;">
Try on outfits virtually, preview styles before you buy, and discover a
smarter, more personal way to shop.
</p>

<!-- Highlight card -->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
style="background:#FAF5FF;border-radius:14px;margin:0 0 28px 0;">
<tr>
<td style="padding:22px 24px;border-left:4px solid #9333EA;border-radius:14px;">
<p style="margin:0 0 8px 0;color:#5B21FF;font-weight:700;font-size:14px;">
✨ Thank you for being part of the VirtuFit Testing Phase
</p>
<p style="margin:0;color:#666666;font-size:14px;line-height:1.7;">
Your feedback is helping us shape the future of virtual fashion.
Every login and every try-on brings us a step closer to a smarter
way to shop online.
</p>
</td>
</tr>
</table>

<!-- CTA button -->
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto 28px auto;">
<tr>
<td align="center" style="border-radius:10px;background:linear-gradient(135deg,#EC1A9E,#5B21FF);">
<a href="https://virtufit.in"
style="display:inline-block;padding:14px 36px;color:#ffffff;text-decoration:none;
font-weight:700;font-size:15px;border-radius:10px;">
Visit VirtuFit →
</a>
</td>
</tr>
</table>

<p style="font-size:13px;color:#999999;line-height:1.7;margin:0;text-align:center;">
If this sign-in wasn't you, please change your password immediately
to keep your account secure.
</p>

</td>
</tr>

<!-- Dotted divider -->
<tr>
<td align="center" style="padding:0 40px;">
<table role="presentation" cellpadding="0" cellspacing="0" width="100%">
<tr>
<td style="border-top:2px dotted #D8B4FE;font-size:0;line-height:0;">&nbsp;</td>
</tr>
</table>
</td>
</tr>

<!-- Footer -->
<tr>
<td align="center" style="padding:24px 40px 32px 40px;">
<p style="font-size:13px;color:#999999;margin:0 0 4px 0;">
© 2026 VirtuFit · AI Virtual Dressing Room
</p>
<p style="font-size:12px;color:#bbbbbb;margin:0;">
This is an automated login notification — no action is needed if this was you.
</p>
</td>
</tr>

</table>

</td>
</tr>
</table>

</body>
</html>
"""
    alt.attach(MIMEText(body, "html"))

    if _logo_bytes:
        logo_img = MIMEImage(_logo_bytes, _subtype="png")
        logo_img.add_header("Content-ID", "<virtufit_logo>")
        logo_img.add_header("Content-Disposition", "inline", filename="virtufit_logo.png")
        msg.attach(logo_img)

    return msg


def _send_once(msg, use_ssl):
    ctx = ssl.create_default_context()
    if use_ssl:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT_SSL, timeout=SMTP_TIMEOUT_SECONDS, context=ctx) as smtp:
            smtp.login(EMAIL, PASSWORD)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT_STARTTLS, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
            smtp.login(EMAIL, PASSWORD)
            smtp.send_message(msg)


def send_login_email(name, user_email):
    """Best-effort login notification. Returns True/False and NEVER raises,
    so a mail problem can't surface as an ASGI exception in the background task."""
    if not EMAIL or not PASSWORD:
        print("❌ Email not configured: set VIRTUFIT_EMAIL and VIRTUFIT_APP_PASSWORD.")
        return False

    try:
        msg = _build_message(name, user_email)
    except Exception as e:
        print("❌ Could not build email:", repr(e))
        return False

    last_err = None
    for attempt in range(1, SMTP_ATTEMPTS + 1):
        use_ssl = attempt == SMTP_ATTEMPTS  # last attempt: try port 465 instead
        try:
            _send_once(msg, use_ssl)
            print(f"✅ Email sent successfully (attempt {attempt}, {'465/SSL' if use_ssl else '587/STARTTLS'}).")
            return True
        except smtplib.SMTPAuthenticationError as e:
            # Wrong/revoked App Password — retrying won't help.
            print("❌ SMTP authentication failed. Use a Gmail App Password:", e)
            return False
        except smtplib.SMTPRecipientsRefused as e:
            print("❌ Recipient refused:", e)
            return False
        except (smtplib.SMTPException, TimeoutError, OSError) as e:
            last_err = e
            print(f"⚠️  Email attempt {attempt}/{SMTP_ATTEMPTS} failed: {repr(e)}")
            if attempt < SMTP_ATTEMPTS:
                time.sleep(2 * attempt)  # 2s, 4s backoff

    print("❌ Email error after all retries:", repr(last_err))
    return False


if __name__ == "__main__":
    # Real send — use your own address when testing.
    send_login_email("Alex", "recipient@example.com")
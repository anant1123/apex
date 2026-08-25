"""
services/email_sender.py — Sends the OTP login code via Resend's HTTP API.

NOT SMTP. Render's free web services block outbound SMTP ports (25, 465,
587) as of Sept 2025 — see https://render.com/changelog — so smtplib
connections just time out there ("upgrade to a paid plan" is Render's own
message for this, not this app's). Resend's REST API sends over plain
HTTPS instead, which is never blocked, and its free tier (100 emails/day,
3,000/month, no credit card) works both locally and on Render.

IMPORTANT LIMITATION: until you verify your own domain at
resend.com/domains, Resend only lets you send FROM their sandbox address
(onboarding@resend.dev) TO the single email address your Resend account
itself is registered with — every other recipient gets silently rejected.
That's fine for logging in as yourself while building/testing, but if you
need classmates/graders to log in with THEIR OWN emails, you'll need to
verify a domain (requires owning one) — or switch this file to Brevo
instead, which only requires verifying a sender email (no domain purchase)
and can email any recipient right away.
"""

import requests
import config

RESEND_ENDPOINT = "https://api.resend.com/emails"


def send_otp_email(to_email, code):
    """Returns True on success, False on failure (caller decides how to react —
    see app.py, which shows the user a friendly error instead of crashing)."""
    if not config.RESEND_API_KEY or not config.RESEND_FROM_EMAIL:
        print("[email_sender] RESEND_API_KEY/RESEND_FROM_EMAIL not set — cannot send OTP email.")
        return False

    html_body = f"""\
<div style="font-family:Arial,sans-serif;background:#0b0b13;padding:32px;color:#eef0f6;">
  <div style="max-width:420px;margin:0 auto;background:rgba(255,255,255,0.04);
              border:1px solid rgba(255,255,255,0.09);border-radius:14px;padding:28px;">
    <h2 style="margin:0 0 8px;letter-spacing:0.04em;">A.P.E.X.</h2>
    <p style="color:#9aa0b4;margin:0 0 24px;">Artificial Processing Educational eXpert</p>
    <p style="margin:0 0 8px;">Your login code is:</p>
    <div style="font-size:32px;font-weight:700;letter-spacing:0.3em;
                color:#06b6d4;margin:0 0 24px;">{code}</div>
    <p style="color:#9aa0b4;font-size:13px;margin:0;">
      Expires in {config.OTP_EXPIRY_MINUTES} minutes. Didn't request this? Ignore this email.
    </p>
  </div>
</div>
"""
    text_body = (
        f"Your A.P.E.X. login code is: {code}\n\n"
        f"This code expires in {config.OTP_EXPIRY_MINUTES} minutes.\n"
        f"If you didn't request this, you can safely ignore this email."
    )

    payload = {
        "from": f"{config.RESEND_FROM_NAME} <{config.RESEND_FROM_EMAIL}>",
        "to": [to_email],
        "subject": f"{code} is your A.P.E.X. login code",
        "html": html_body,
        "text": text_body,
    }
    headers = {
        "Authorization": f"Bearer {config.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(RESEND_ENDPOINT, json=payload, headers=headers, timeout=10)
        if resp.status_code in (200, 201):
            return True
        print(f"[email_sender] Resend API error {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        print(f"[email_sender] Failed to send OTP email: {e}")
        return False

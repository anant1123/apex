"""
services/email_sender.py — Sends the OTP login code via SMTP.

Plain smtplib (stdlib) — no new dependency. Works with Gmail (App
Password), Brevo, Resend's SMTP endpoint, or any other SMTP provider by
just changing the SMTP_* env vars in config.py.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import config


def send_otp_email(to_email, code):
    """Returns True on success, False on failure (caller decides how to react —
    see app.py, which shows the user a friendly error instead of crashing)."""
    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        print("[email_sender] SMTP_USER/SMTP_PASSWORD not set — cannot send OTP email.")
        return False

    subject = f"{code} is your A.P.E.X. login code"
    text_body = (
        f"Your A.P.E.X. login code is: {code}\n\n"
        f"This code expires in {config.OTP_EXPIRY_MINUTES} minutes.\n"
        f"If you didn't request this, you can safely ignore this email."
    )
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

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{config.SMTP_FROM_NAME} <{config.SMTP_USER}>"
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            # server.sendmail(config.SMTP_USER, [to_email], msg.as_string())
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[email_sender] Failed to send OTP email: {e}")
        return False

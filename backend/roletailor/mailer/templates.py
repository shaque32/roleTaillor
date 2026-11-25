"""The three account emails. Plain layout, inline styles, a text part for every message."""

from __future__ import annotations

from html import escape

from roletailor.mailer.provider import EmailMessage

_BRAND = "#4f46e5"


def _first_name(full_name: str | None) -> str:
    parts = (full_name or "").split()
    return parts[0][:60] if parts else "there"


def _html(heading: str, paragraphs: list[str], button: tuple[str, str] | None, footer: str) -> str:
    body = "".join(f'<p style="margin:0 0 16px">{escape(p)}</p>' for p in paragraphs)
    action = ""
    if button:
        label, url = button
        action = (
            f'<p style="margin:24px 0"><a href="{escape(url, quote=True)}" style="background:{_BRAND};'
            'color:#ffffff;text-decoration:none;padding:12px 20px;border-radius:8px;font-weight:600;'
            f'display:inline-block">{escape(label)}</a></p>'
            '<p style="margin:0 0 16px;font-size:13px;color:#64748b">If the button does not work, copy this'
            f' link into your browser:<br><span style="word-break:break-all">{escape(url)}</span></p>'
        )
    return (
        '<!doctype html><html><body style="margin:0;background:#f8fafc;font-family:-apple-system,'
        "BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#0f172a;font-size:15px;"
        'line-height:1.55"><div style="max-width:520px;margin:0 auto;padding:32px 20px">'
        '<p style="margin:0 0 24px;font-weight:700;font-size:17px">RoleTailor</p>'
        '<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:28px">'
        f'<h1 style="margin:0 0 16px;font-size:20px">{escape(heading)}</h1>{body}{action}</div>'
        f'<p style="margin:20px 0 0;font-size:12px;color:#64748b">{escape(footer)}</p>'
        "</div></body></html>"
    )


def _text(paragraphs: list[str], url: str | None, footer: str) -> str:
    parts = list(paragraphs)
    if url:
        parts.append(url)
    parts.append(footer)
    return "\n\n".join(parts) + "\n"


def verification(to: str, full_name: str | None, url: str, ttl_hours: int) -> EmailMessage:
    paragraphs = [
        f"Hi {_first_name(full_name)},",
        "Confirm this email address to start tailoring your resume with RoleTailor."
        f" The link works once and expires in {ttl_hours} hours.",
    ]
    footer = "If you did not create a RoleTailor account, you can ignore this email."
    return EmailMessage(
        to=to, subject="Confirm your email for RoleTailor", kind="verify_email",
        text=_text(paragraphs, url, footer),
        html=_html("Confirm your email", paragraphs, ("Confirm email", url), footer),
    )


def password_reset(to: str, full_name: str | None, url: str, ttl_minutes: int) -> EmailMessage:
    paragraphs = [
        f"Hi {_first_name(full_name)},",
        "We received a request to reset your RoleTailor password."
        f" The link works once and expires in {ttl_minutes} minutes.",
    ]
    footer = ("If you did not ask for this, you can ignore this email."
              " Your password stays the same until the link is used.")
    return EmailMessage(
        to=to, subject="Reset your RoleTailor password", kind="reset_password",
        text=_text(paragraphs, url, footer),
        html=_html("Reset your password", paragraphs, ("Choose a new password", url), footer),
    )


def password_changed(to: str, full_name: str | None, reset_url: str) -> EmailMessage:
    paragraphs = [
        f"Hi {_first_name(full_name)},",
        "Your RoleTailor password was just changed, and every device was signed out.",
        "If this was not you, reset your password now:",
    ]
    footer = "You are receiving this because the password on your RoleTailor account changed."
    return EmailMessage(
        to=to, subject="Your RoleTailor password was changed", kind="password_changed",
        text=_text(paragraphs, reset_url, footer),
        html=_html("Your password was changed", paragraphs, ("Reset password", reset_url), footer),
    )

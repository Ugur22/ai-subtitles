"""
Email service for verification codes and password resets.

Supports real SMTP email sending or fallback to console logging.
Configure via environment variables: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
"""
import os
import random
import logging
from typing import Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    import aiosmtplib
    AIOSMTPLIB_AVAILABLE = True
except ImportError:
    AIOSMTPLIB_AVAILABLE = False
    logging.warning("aiosmtplib not installed. Email sending will fall back to console logging.")

logger = logging.getLogger(__name__)


def generate_verification_code() -> str:
    """
    Generate a 6-digit verification code.

    Returns:
        6-digit string code
    """
    return str(random.randint(100000, 999999))


def _is_smtp_configured() -> bool:
    """Check if SMTP environment variables are configured."""
    required_vars = ['SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_FROM']
    return all(os.environ.get(var) for var in required_vars)


def _create_email_message(to_email: str, subject: str, html_content: str) -> MIMEMultipart:
    """
    Create a MIME multipart email message.

    Args:
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML body content

    Returns:
        MIMEMultipart message
    """
    message = MIMEMultipart('alternative')
    message['From'] = os.environ.get('SMTP_FROM', 'noreply@ai-subs.com')
    message['To'] = to_email
    message['Subject'] = subject

    # Create plain text version by stripping HTML tags (basic)
    text_content = html_content.replace('<br>', '\n').replace('</p>', '\n')
    text_content = text_content.replace('<strong>', '').replace('</strong>', '')
    # Remove remaining HTML tags
    import re
    text_content = re.sub('<[^<]+?>', '', text_content).strip()

    part1 = MIMEText(text_content, 'plain')
    part2 = MIMEText(html_content, 'html')

    message.attach(part1)
    message.attach(part2)

    return message


async def _send_smtp_email(to_email: str, subject: str, html_content: str) -> bool:
    """
    Send email via SMTP.

    Args:
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML body content

    Returns:
        True if sent successfully, False otherwise
    """
    if not AIOSMTPLIB_AVAILABLE:
        logger.warning("aiosmtplib not available. Install with: pip install aiosmtplib")
        return False

    if not _is_smtp_configured():
        logger.warning("SMTP not configured. Missing environment variables: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM")
        return False

    try:
        smtp_host = os.environ.get('SMTP_HOST')
        smtp_port = int(os.environ.get('SMTP_PORT', '587'))
        smtp_user = os.environ.get('SMTP_USER')
        smtp_password = os.environ.get('SMTP_PASSWORD')

        message = _create_email_message(to_email, subject, html_content)

        # Connect and send
        await aiosmtplib.send(
            message,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_password,
            start_tls=True,
            timeout=10
        )

        logger.info(f"Email sent successfully to {to_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False


def _log_email_to_console(email: str, subject: str, code: str, message: str):
    """
    Fallback: Log email details to console.

    Args:
        email: Recipient email
        subject: Email subject
        code: Verification/reset code
        message: Additional message
    """
    print(f"\n{'='*60}")
    print(f"{subject}")
    print(f"{'='*60}")
    print(f"To: {email}")
    print(f"Code: {code}")
    print(f"\n{message}")
    print(f"{'='*60}\n")


async def send_verification_email(email: str, code: str) -> bool:
    """
    Send email verification code.

    Args:
        email: User's email address
        code: 6-digit verification code

    Returns:
        True if sent successfully (or logged to console)
    """
    subject = "Verify your email - AI-Subs"
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
          <h2 style="color: #4F46E5;">Verify Your Email</h2>
          <p>Thank you for registering with AI-Subs!</p>
          <p>Your verification code is:</p>
          <div style="background-color: #F3F4F6; padding: 20px; text-align: center; border-radius: 8px; margin: 20px 0;">
            <span style="font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #4F46E5;">{code}</span>
          </div>
          <p>This code will expire in <strong>15 minutes</strong>.</p>
          <p>If you didn't request this verification, please ignore this email.</p>
          <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 30px 0;">
          <p style="font-size: 12px; color: #6B7280;">
            This is an automated email from AI-Subs. Please do not reply to this message.
          </p>
        </div>
      </body>
    </html>
    """

    # Try SMTP first, fall back to console
    if _is_smtp_configured() and AIOSMTPLIB_AVAILABLE:
        success = await _send_smtp_email(email, subject, html_content)
        if success:
            return True
        logger.warning(f"SMTP failed for {email}, falling back to console logging")

    # Fallback to console
    _log_email_to_console(
        email,
        "EMAIL VERIFICATION CODE",
        code,
        "Please verify your email by entering this code.\nThis code will expire in 15 minutes."
    )
    return True


async def send_password_reset_email(email: str, code: str) -> bool:
    """
    Send password reset code.

    Args:
        email: User's email address
        code: 6-digit reset code

    Returns:
        True if sent successfully (or logged to console)
    """
    subject = "Reset your password - AI-Subs"
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
          <h2 style="color: #4F46E5;">Reset Your Password</h2>
          <p>We received a request to reset your password.</p>
          <p>Your password reset code is:</p>
          <div style="background-color: #F3F4F6; padding: 20px; text-align: center; border-radius: 8px; margin: 20px 0;">
            <span style="font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #4F46E5;">{code}</span>
          </div>
          <p>This code will expire in <strong>15 minutes</strong>.</p>
          <p style="color: #DC2626; font-weight: bold;">
            If you didn't request this password reset, please ignore this email and your password will remain unchanged.
          </p>
          <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 30px 0;">
          <p style="font-size: 12px; color: #6B7280;">
            This is an automated email from AI-Subs. Please do not reply to this message.
          </p>
        </div>
      </body>
    </html>
    """

    # Try SMTP first, fall back to console
    if _is_smtp_configured() and AIOSMTPLIB_AVAILABLE:
        success = await _send_smtp_email(email, subject, html_content)
        if success:
            return True
        logger.warning(f"SMTP failed for {email}, falling back to console logging")

    # Fallback to console
    _log_email_to_console(
        email,
        "PASSWORD RESET CODE",
        code,
        "Use this code to reset your password.\nThis code will expire in 15 minutes.\nIf you didn't request this, please ignore this email."
    )
    return True


async def send_welcome_email(email: str, display_name: Optional[str] = None) -> bool:
    """
    Send welcome email after successful registration.

    Args:
        email: User's email address
        display_name: Optional display name

    Returns:
        True if sent successfully (or logged to console)
    """
    name = display_name or email.split('@')[0]
    subject = "Welcome to AI-Subs!"
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
          <h2 style="color: #4F46E5;">Welcome to AI-Subs, {name}!</h2>
          <p>Your account has been created successfully.</p>
          <p>You can now:</p>
          <ul style="line-height: 2;">
            <li>Upload videos for AI-powered transcription</li>
            <li>Use speaker diarization to identify different speakers</li>
            <li>Generate subtitles automatically</li>
            <li>Chat with AI about your video content</li>
          </ul>
          <p>Get started by configuring your API keys in the settings panel.</p>
          <div style="margin: 30px 0; text-align: center;">
            <a href="https://ai-subs.com" style="background-color: #4F46E5; color: white; padding: 12px 30px; text-decoration: none; border-radius: 6px; display: inline-block;">
              Go to AI-Subs
            </a>
          </div>
          <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 30px 0;">
          <p style="font-size: 12px; color: #6B7280;">
            This is an automated email from AI-Subs. Please do not reply to this message.
          </p>
        </div>
      </body>
    </html>
    """

    # Try SMTP first, fall back to console
    if _is_smtp_configured() and AIOSMTPLIB_AVAILABLE:
        success = await _send_smtp_email(email, subject, html_content)
        if success:
            return True
        logger.warning(f"SMTP failed for {email}, falling back to console logging")

    # Fallback to console
    print(f"\n{'='*60}")
    print(f"WELCOME EMAIL")
    print(f"{'='*60}")
    print(f"To: {email}")
    print(f"\nWelcome to AI-Subs, {name}!")
    print(f"\nYour account has been created successfully.")
    print(f"You can now upload videos and use AI-powered transcription.")
    print(f"{'='*60}\n")

    return True

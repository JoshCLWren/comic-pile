//! Password-recovery email delivery for the native Rust authentication surface.
//!
//! Behavior mirrors `app/services/password_reset_mailer.py`: the same subject,
//! body and reset-link shape are composed here, and Gmail SMTP is used when
//! `GMAIL_SMTP_USERNAME` and `GMAIL_SMTP_APP_PASSWORD` are configured. When they
//! are absent the request still succeeds and the delivery attempt is skipped
//! with an operational log, matching the Python fake-mailer fallback.
//!
//! The raw reset token is used only to build the link. It is never persisted or
//! logged by this module.

use std::time::Duration;

use chrono::{DateTime, Utc};
use lettre::{
    message::Mailbox,
    transport::smtp::authentication::Credentials,
    transport::smtp::client::{Tls, TlsParameters},
    AsyncSmtpTransport, AsyncTransport, Message, Tokio1Executor,
};

use crate::auth::services::ResetDelivery;

const RESET_SUBJECT: &str = "Reset your Comic Pile password";
const PRODUCTION_RESET_ORIGIN: &str = "https://comic-pile.vercel.app";
const NON_PRODUCTION_RESET_ORIGIN: &str = "http://localhost:3000";
const GMAIL_SMTP_HOST: &str = "smtp.gmail.com";
const GMAIL_SMTP_PORT: u16 = 465;
const SMTP_TIMEOUT_SECONDS: u64 = 10;
const EXPIRY_MINUTES: i64 = 30;

/// Compose the user-facing reset URL at the delivery boundary.
pub fn build_password_reset_url(origin: &str, path: &str, raw_token: &str) -> String {
    let origin = origin.trim().trim_end_matches('/');
    let mut path = path.trim();
    if path.is_empty() {
        path = "/reset-password";
    }
    let path = if path.starts_with('/') {
        path.to_string()
    } else {
        format!("/{path}")
    };
    format!("{origin}{path}?token={}", percent_encode(raw_token))
}

/// Return the fixed password-reset email subject.
pub fn build_password_reset_subject() -> &'static str {
    RESET_SUBJECT
}

/// Compose the minimal plaintext reset message, matching the Python copy.
pub fn build_password_reset_text_body(
    username: &str,
    reset_url: &str,
    expires_at: DateTime<Utc>,
) -> String {
    let expiry_display = expires_at.format("%Y-%m-%d %H:%M UTC");
    format!(
        "Hi {username},\n\
         \n\
         Someone requested a password reset for your Comic Pile account.\n\
         Use the link below to choose a new password:\n\
         \n\
         {reset_url}\n\
         \n\
         This link expires in {EXPIRY_MINUTES} minutes \
         (around {expiry_display}) and can be used only once.\n\
         If you did not request a reset, you can safely ignore this message — \
         your password has not changed.\n\
         Never share this link with anyone; it grants access to your account.\n"
    )
}

fn percent_encode(value: &str) -> String {
    let mut encoded = String::with_capacity(value.len());
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b'~') {
            encoded.push(byte as char);
        } else {
            encoded.push_str(&format!("%{byte:02X}"));
        }
    }
    encoded
}

struct SmtpSettings {
    username: String,
    app_password: String,
    sender: String,
    origin: String,
    path: String,
}

fn environment_value(name: &str) -> Option<String> {
    std::env::var(name)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn smtp_settings() -> Option<SmtpSettings> {
    let username = environment_value("GMAIL_SMTP_USERNAME")?;
    let app_password = environment_value("GMAIL_SMTP_APP_PASSWORD")?;
    let production = environment_value("ENVIRONMENT").as_deref() == Some("production");
    let default_origin = if production {
        PRODUCTION_RESET_ORIGIN
    } else {
        NON_PRODUCTION_RESET_ORIGIN
    };
    let sender = environment_value("PASSWORD_RESET_SENDER")
        .unwrap_or_else(|| format!("Comic Pile <{username}>"));
    let origin =
        environment_value("PASSWORD_RESET_ORIGIN").unwrap_or_else(|| default_origin.into());
    let path = environment_value("PASSWORD_RESET_PATH").unwrap_or_else(|| "/reset-password".into());
    Some(SmtpSettings {
        username,
        app_password,
        sender,
        origin,
        path,
    })
}

/// Deliver one reset message. Failures are logged as status only, never with
/// the recipient, token or provider error text.
pub async fn deliver(delivery: ResetDelivery) {
    let Some(settings) = smtp_settings() else {
        tracing::warn!(
            event = "password_reset_email_unconfigured",
            "Password reset email was not sent: outbound email is not configured."
        );
        return;
    };
    let reset_url = build_password_reset_url(&settings.origin, &settings.path, &delivery.token);
    let body = build_password_reset_text_body(&delivery.username, &reset_url, delivery.expires_at);
    let message = build_message(&settings.sender, &delivery.recipient_email, body);
    let Ok(message) = message else {
        tracing::warn!(
            event = "password_reset_delivery_failed",
            "Password reset email delivery failed: invalid message."
        );
        return;
    };
    let Ok(tls) = TlsParameters::new(GMAIL_SMTP_HOST.to_string()) else {
        tracing::warn!(
            event = "password_reset_delivery_failed",
            "Password reset email delivery failed: TLS setup."
        );
        return;
    };
    let transport = AsyncSmtpTransport::<Tokio1Executor>::builder_dangerous(GMAIL_SMTP_HOST)
        .port(GMAIL_SMTP_PORT)
        .tls(Tls::Wrapper(tls))
        .credentials(Credentials::new(settings.username, settings.app_password))
        .timeout(Some(Duration::from_secs(SMTP_TIMEOUT_SECONDS)))
        .build();
    match transport.send(message).await {
        Ok(_) => tracing::info!(
            event = "password_reset_email_sent",
            "Password reset email accepted by provider."
        ),
        Err(_) => tracing::warn!(
            event = "password_reset_delivery_failed",
            "Password reset email delivery failed."
        ),
    }
}

fn build_message(sender: &str, recipient: &str, body: String) -> Result<Message, ()> {
    let from: Mailbox = sender.parse().map_err(|_| ())?;
    let to: Mailbox = recipient.parse().map_err(|_| ())?;
    Message::builder()
        .from(from)
        .to(to)
        .subject(RESET_SUBJECT)
        .body(body)
        .map_err(|_| ())
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    #[test]
    fn reset_url_and_body_match_the_python_contract() {
        let url = build_password_reset_url(
            "https://comic-pile.vercel.app/",
            "reset-password",
            "abc_DEF-123",
        );
        assert_eq!(
            url,
            "https://comic-pile.vercel.app/reset-password?token=abc_DEF-123"
        );
        let expires = Utc.with_ymd_and_hms(2026, 11, 1, 22, 0, 0).unwrap();
        let body = build_password_reset_text_body("reader", &url, expires);
        assert!(body.starts_with("Hi reader,\n"));
        assert!(body.contains("This link expires in 30 minutes"));
        assert!(body.contains("(around 2026-11-01 22:00 UTC)"));
        assert!(body.contains(&url));
        assert_eq!(build_password_reset_subject(), RESET_SUBJECT);
    }

    #[test]
    fn token_is_percent_encoded_in_the_link() {
        assert_eq!(
            build_password_reset_url("https://example.test", "/reset", "a+b/c"),
            "https://example.test/reset?token=a%2Bb%2Fc"
        );
    }
}

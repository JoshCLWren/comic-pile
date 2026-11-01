//! First-party authentication for the native Rust API.
//!
//! The account lifecycle (register, login, refresh, logout, CSRF, current user)
//! is implemented here and mounted under `/api/v2/auth`. Password-recovery
//! delivery still lives in Python until an equivalent Rust mailer is added; the
//! shared JWT, password-epoch and reset-digest contracts remain compatible.

pub mod dto;
pub mod error;
pub mod handlers;
pub mod identity;
pub mod middleware;
pub mod services;
pub mod utils;

pub use dto::*;
pub use error::{AuthError, AuthResult};
pub use handlers::*;
pub use identity::{authenticate, AuthenticatedUser};
pub use services::{AuthService, PasswordResetService};
pub use utils::{generate_csrf_token, hash_password, verify_password};

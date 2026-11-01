//! First-party authentication for the native Rust API.
//!
//! The full account lifecycle (register, login, refresh, logout, CSRF, current
//! user) and password recovery (forgot/reset with native email delivery) is
//! implemented here and mounted under `/api/v2/auth`. The shared JWT,
//! password-epoch and reset-digest contracts remain Python-compatible.

mod delivery;
pub mod dto;
pub mod error;
pub mod handlers;
pub mod identity;
pub mod mailer;
pub mod middleware;
pub mod services;
pub mod utils;

pub use delivery::BackgroundTasks;
pub use dto::*;
pub use error::{AuthError, AuthResult};
pub use handlers::*;
pub use identity::{authenticate, AuthenticatedUser};
pub use services::{AuthService, PasswordResetService};
pub use utils::{generate_csrf_token, hash_password, verify_password};

//! Complete authentication module for Rust v2
//! 
//! This module provides all authentication functionality previously implemented in Python and Node.js:
//! - User registration, login, logout
//! - JWT token management (access, refresh, revocation)
//! - Password reset flow
//! - CSRF protection
//! - Rate limiting and security features
//! 
//! The implementation follows the existing Python semantics while providing security hardening.

pub mod dto;
pub mod identity;
pub mod error;
pub mod handlers;
pub mod middleware;
pub mod services;
pub mod utils;

pub use dto::*;
pub use error::{AuthError, AuthResult};
pub use handlers::*;
pub use identity::AuthenticatedUser;
pub use middleware::CsrfToken;
pub use services::{AuthService, PasswordResetService};
pub use utils::{hash_password, verify_password, generate_csrf_token};
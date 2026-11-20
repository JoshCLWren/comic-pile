//! Validated startup configuration. Credential-bearing inputs never implement Debug.
use std::{net::SocketAddr, str::FromStr, time::Duration};
use tokio_postgres::{config::SslMode, Config as PostgresConfig};
use tracing_subscriber::EnvFilter;

/// Deployment environment determines binding and transport requirements.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Environment {
    Development,
    Production,
}

/// Configuration errors contain only static descriptions, never input values.
#[derive(Debug)]
pub struct ConfigError(pub &'static str);
impl std::fmt::Display for ConfigError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.0)
    }
}
impl std::error::Error for ConfigError {}

/// Secret reserved for authenticated handlers; intentionally has no Debug implementation.
pub struct JwtSecret(String);
impl JwtSecret {
    pub fn as_bytes(&self) -> &[u8] {
        self.0.as_bytes()
    }
}

/// Typed settings shared by startup and later authenticated request handlers.
pub struct Config {
    pub environment: Environment,
    pub bind: SocketAddr,
    pub database: PostgresConfig,
    pub jwt_secret: JwtSecret,
    /// HMAC secret for series-mapping preview tokens.
    pub preview_token_secret: String,
    pub log_filter: EnvFilter,
    pub pool_size: usize,
    pub pool_timeout: Duration,
    pub request_timeout: Duration,
    /// Access-token lifetime, matching Python's ACCESS_TOKEN_EXPIRE_MINUTES.
    pub access_token_expire_minutes: i64,
    /// Refresh-token and refresh-cookie lifetime, matching Python's
    /// REFRESH_TOKEN_EXPIRE_DAYS.
    pub refresh_token_expire_days: i64,
}
/// Adapt SQLAlchemy/Neon URLs for tokio-postgres. The production DATABASE_URL
/// can contain libpq/driver options that tokio-postgres does not recognize.
/// This endpoint needs the authority, database, credentials and TLS. Drop only
/// query options: never log or alter any credential-bearing URI components.
/// Explicit insecure sslmode remains rejected by production validation.
fn vercel_postgres_url(raw: String) -> String {
    let raw = raw.trim();
    let url = [
        "postgresql+asyncpg://",
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
        "postgres://",
    ]
    .iter()
    .find_map(|prefix| raw.strip_prefix(prefix))
    .map(|rest| format!("postgresql://{rest}"))
    .unwrap_or_else(|| raw.to_owned());

    let (base, query) = url.split_once('?').unwrap_or((&url, ""));
    let mode = query
        .split('&')
        .filter_map(|part| part.split_once('='))
        .find_map(|(key, value)| (key == "sslmode").then_some(value))
        .unwrap_or("require");
    // native-tls validates server certificates and hostnames even though
    // tokio-postgres uses its Require variant for the encrypted connection.
    let mode = match mode {
        "verify-ca" | "verify-full" => "require",
        other => other,
    };
    format!("{base}?sslmode={mode}")
}

impl Config {
    pub fn from_env() -> Result<Self, ConfigError> {
        Self::from_lookup(|name| std::env::var(name).ok())
    }

    /// Production Vercel Roll entrypoint: existing DATABASE_URL and SECRET_KEY
    /// unless native-specific overrides are configured.
    pub fn from_vercel_env() -> Result<Self, ConfigError> {
        Self::from_vercel_lookup(|name| std::env::var(name).ok())
    }

    /// Injectable variant for credential-free startup tests.
    pub fn from_vercel_lookup(get: impl Fn(&str) -> Option<String>) -> Result<Self, ConfigError> {
        Self::from_lookup(|name| match name {
            "RUST_ROLL_ENV" => get(name).or_else(|| Some("production".into())),
            "RUST_ROLL_DATABASE_URL" => get(name)
                .or_else(|| get("DATABASE_URL"))
                .map(vercel_postgres_url),
            "RUST_ROLL_JWT_SECRET" => get(name).or_else(|| get("SECRET_KEY")),
            _ => get(name),
        })
    }

    /// Injectable lookup keeps tests independent of process-global environment mutations.
    pub fn from_lookup(get: impl Fn(&str) -> Option<String>) -> Result<Self, ConfigError> {
        let environment = match get("RUST_ROLL_ENV").as_deref().unwrap_or("development") {
            "development" => Environment::Development,
            "production" => Environment::Production,
            _ => {
                return Err(ConfigError(
                    "RUST_ROLL_ENV must be development or production",
                ))
            }
        };
        let bind = get("RUST_ROLL_BIND")
            .unwrap_or_else(|| "127.0.0.1:8010".into())
            .parse::<SocketAddr>()
            .map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                ConfigError("invalid RUST_ROLL_BIND")
            })?;
        if environment == Environment::Development && !bind.ip().is_loopback() {
            return Err(ConfigError("development binding must be loopback"));
        }
        let database = PostgresConfig::from_str(
            &get("RUST_ROLL_DATABASE_URL").ok_or(ConfigError("RUST_ROLL_DATABASE_URL required"))?,
        )
        .map_err(|e| {
            tracing::debug!(
                error_kind = crate::error_kind(&e),
                "preserved underlying error before mapping"
            );
            ConfigError("invalid RUST_ROLL_DATABASE_URL")
        })?;
        if environment == Environment::Production && database.get_ssl_mode() != SslMode::Require {
            return Err(ConfigError("production database requires sslmode=require"));
        }
        let jwt_secret = get("RUST_ROLL_JWT_SECRET")
            .filter(|value| !value.trim().is_empty())
            .ok_or(ConfigError("RUST_ROLL_JWT_SECRET required"))?;
        let preview_token_secret = get("PREVIEW_TOKEN_SECRET_KEY")
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
            .unwrap_or_else(|| jwt_secret.clone());
        let log_filter = EnvFilter::try_new(get("RUST_ROLL_LOG").unwrap_or_else(|| "info".into()))
            .map_err(|e| {
                tracing::debug!(
                    error_kind = crate::error_kind(&e),
                    "preserved underlying error before mapping"
                );
                ConfigError("invalid RUST_ROLL_LOG")
            })?;
        fn number(
            get: &impl Fn(&str) -> Option<String>,
            name: &'static str,
            default: u64,
            max: u64,
        ) -> Result<u64, ConfigError> {
            let value = get(name)
                .map(|value| value.parse::<u64>())
                .transpose()
                .map_err(|e| {
                    tracing::debug!(
                        error_kind = crate::error_kind(&e),
                        "preserved underlying error before mapping"
                    );
                    ConfigError("invalid numeric pool or timeout setting")
                })?
                .unwrap_or(default);
            if value == 0 || value > max {
                return Err(ConfigError("pool or timeout setting outside allowed range"));
            }
            Ok(value)
        }
        Ok(Self {
            environment,
            bind,
            database,
            jwt_secret: JwtSecret(jwt_secret),
            preview_token_secret,
            log_filter,
            pool_size: number(&get, "RUST_ROLL_POOL_SIZE", 4, 32)? as usize,
            pool_timeout: Duration::from_millis(number(
                &get,
                "RUST_ROLL_POOL_TIMEOUT_MS",
                2000,
                30000,
            )?),
            request_timeout: Duration::from_millis(number(
                &get,
                "RUST_ROLL_REQUEST_TIMEOUT_MS",
                10000,
                60000,
            )?),
            // Python defaults: 12 hours access, 7 days refresh. Read the same
            // environment names so Rust and any still-Python path agree.
            access_token_expire_minutes: number(
                &get,
                "ACCESS_TOKEN_EXPIRE_MINUTES",
                720,
                7 * 24 * 60,
            )? as i64,
            refresh_token_expire_days: number(&get, "REFRESH_TOKEN_EXPIRE_DAYS", 7, 365)? as i64,
        })
    }
}

#[cfg(test)]
mod vercel_tests {
    use super::*;

    #[test]
    fn existing_neon_url_and_python_secret_boot_native_config() {
        let config = Config::from_vercel_lookup(|key| match key {
            "DATABASE_URL" => Some(
                concat!(
                    "postgresql+asyncpg://reader:password@ep-example.us-east-2.aws.neon.tech/",
                    "neondb?sslmode=require&channel_binding=require"
                )
                .into(),
            ),
            "SECRET_KEY" => Some("synthetic-jwt-key".into()),
            _ => None,
        })
        .expect("Python production environment must bootstrap native Roll");
        assert_eq!(config.environment, Environment::Production);
        assert_eq!(config.database.get_ssl_mode(), SslMode::Require);
        assert_eq!(config.database.get_dbname(), Some("neondb"));
        assert_eq!(config.jwt_secret.as_bytes(), b"synthetic-jwt-key");
    }

    #[test]
    fn native_override_and_sqlalchemy_schemes_preserve_tls() {
        for scheme in [
            "postgresql+asyncpg",
            "postgresql+psycopg",
            "postgresql+psycopg2",
            "postgres",
        ] {
            let url = format!("{scheme}://reader:password@localhost/app?channel_binding=require");
            let config = Config::from_vercel_lookup(|key| match key {
                "RUST_ROLL_DATABASE_URL" => Some(url.clone()),
                "RUST_ROLL_JWT_SECRET" => Some("native-override".into()),
                "SECRET_KEY" => Some("python-secret".into()),
                _ => None,
            })
            .expect("known SQLAlchemy dialect should normalize");
            assert_eq!(config.database.get_ssl_mode(), SslMode::Require);
            assert_eq!(config.jwt_secret.as_bytes(), b"native-override");
        }
    }

    #[test]
    fn vercel_neon_extra_parameters_do_not_break_config_parse() {
        let config = Config::from_vercel_lookup(|key| match key {
            "DATABASE_URL" => Some(
                concat!(
                    "postgresql+asyncpg://reader:p%40ssword@ep-example.us-east-2.aws.neon.tech/",
                    "neondb?sslmode=verify-full&channel_binding=require&gssencmode=disable",
                    "&sslrootcert=%2Ftmp%2Fcert&application_name=the-reader"
                )
                .into(),
            ),
            "SECRET_KEY" => Some("synthetic-secret".into()),
            _ => None,
        })
        .expect("production URL with driver-only options must be accepted");
        assert_eq!(config.database.get_ssl_mode(), SslMode::Require);
        assert_eq!(config.database.get_user(), Some("reader"));
        assert_eq!(config.database.get_password(), Some(b"p@ssword".as_slice()));
        assert_eq!(config.database.get_dbname(), Some("neondb"));
    }

    #[test]
    fn rejects_insecure_production_transport() {
        let result = Config::from_vercel_lookup(|key| match key {
            "DATABASE_URL" => {
                Some("postgresql://reader:password@localhost/app?sslmode=disable".into())
            }
            "SECRET_KEY" => Some("synthetic".into()),
            _ => None,
        });
        assert!(result.is_err());
    }

    #[test]
    fn token_lifetimes_match_python_defaults_and_environment_overrides() {
        let base = |key: &str| match key {
            "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/app".into()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic".into()),
            "ACCESS_TOKEN_EXPIRE_MINUTES" => Some("45".into()),
            "REFRESH_TOKEN_EXPIRE_DAYS" => Some("2".into()),
            _ => None,
        };
        let overridden = Config::from_lookup(base).unwrap();
        assert_eq!(overridden.access_token_expire_minutes, 45);
        assert_eq!(overridden.refresh_token_expire_days, 2);

        let defaults = Config::from_lookup(|key| match key {
            "RUST_ROLL_DATABASE_URL" => Some("postgresql://localhost/app".into()),
            "RUST_ROLL_JWT_SECRET" => Some("synthetic".into()),
            _ => None,
        })
        .unwrap();
        assert_eq!(defaults.access_token_expire_minutes, 720);
        assert_eq!(defaults.refresh_token_expire_days, 7);
    }
}

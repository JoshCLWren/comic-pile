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
    pub log_filter: EnvFilter,
    pub pool_size: usize,
    pub pool_timeout: Duration,
    pub request_timeout: Duration,
}
impl Config {
    pub fn from_env() -> Result<Self, ConfigError> {
        Self::from_lookup(|name| std::env::var(name).ok())
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
            .map_err(|_| ConfigError("invalid RUST_ROLL_BIND"))?;
        if environment == Environment::Development && !bind.ip().is_loopback() {
            return Err(ConfigError("development binding must be loopback"));
        }
        let database = PostgresConfig::from_str(
            &get("RUST_ROLL_DATABASE_URL").ok_or(ConfigError("RUST_ROLL_DATABASE_URL required"))?,
        )
        .map_err(|_| ConfigError("invalid RUST_ROLL_DATABASE_URL"))?;
        if environment == Environment::Production && database.get_ssl_mode() != SslMode::Require {
            return Err(ConfigError("production database requires sslmode=require"));
        }
        let jwt_secret = get("RUST_ROLL_JWT_SECRET")
            .filter(|value| !value.trim().is_empty())
            .ok_or(ConfigError("RUST_ROLL_JWT_SECRET required"))?;
        let log_filter = EnvFilter::try_new(get("RUST_ROLL_LOG").unwrap_or_else(|| "info".into()))
            .map_err(|_| ConfigError("invalid RUST_ROLL_LOG"))?;
        fn number(
            get: &impl Fn(&str) -> Option<String>,
            name: &'static str,
            default: u64,
            max: u64,
        ) -> Result<u64, ConfigError> {
            let value = get(name)
                .map(|value| value.parse::<u64>())
                .transpose()
                .map_err(|_| ConfigError("invalid numeric pool or timeout setting"))?
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
        })
    }
}

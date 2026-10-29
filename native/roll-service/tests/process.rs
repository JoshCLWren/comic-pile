//! Process lifecycle evidence: health requires no DB and termination drains cleanly.
#[cfg(unix)]
#[test]
fn serves_health_with_dead_database_and_exits_on_sigterm() {
    check_shutdown(false);
}

#[cfg(unix)]
#[test]
fn incomplete_http_headers_cannot_hold_process_open() {
    check_shutdown(true);
}

#[cfg(unix)]
fn check_shutdown(incomplete_headers: bool) {
    use std::{
        io::{Read, Write},
        net::{TcpListener, TcpStream},
        process::{Command, Stdio},
        thread,
        time::{Duration, Instant},
    };
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    drop(listener);
    let mut child = Command::new(env!("CARGO_BIN_EXE_comicpile-roll-service"))
        .env_clear()
        .env("RUST_ROLL_BIND", address.to_string())
        .env(
            "RUST_ROLL_DATABASE_URL",
            "postgresql://synthetic:private-password@127.0.0.1:1/unused?sslmode=disable",
        )
        .env("RUST_ROLL_JWT_SECRET", "private-jwt-secret")
        .env("RUST_ROLL_REQUEST_TIMEOUT_MS", "50")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    let response = loop {
        if let Ok(mut socket) = TcpStream::connect(address) {
            socket
                .set_read_timeout(Some(Duration::from_secs(1)))
                .unwrap();
            socket.write_all(b"GET /health?token=private-query-secret HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer private-header-secret\r\nConnection: close\r\n\r\n").unwrap();
            let mut response = String::new();
            socket.read_to_string(&mut response).unwrap();
            break response;
        }
        if Instant::now() > deadline {
            let _ = child.kill();
            let output = child.wait_with_output().unwrap();
            panic!(
                "service did not start: {}",
                String::from_utf8_lossy(&output.stderr)
            );
        }
        thread::sleep(Duration::from_millis(10));
    };
    let _stalled = if incomplete_headers {
        let mut socket = TcpStream::connect(address).unwrap();
        socket.write_all(b"GET /health HTTP/1.1\r\nHost: ").unwrap();
        thread::sleep(Duration::from_millis(20));
        Some(socket)
    } else {
        None
    };
    let shutdown_started = Instant::now();
    assert!(response.starts_with("HTTP/1.1 200"));
    assert!(response.contains(r#"{"status":"ok"}"#));
    assert!(Command::new("kill")
        .args(["-TERM", &child.id().to_string()])
        .status()
        .unwrap()
        .success());
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if child.try_wait().unwrap().is_some() {
            break;
        }
        if Instant::now() > deadline {
            let _ = child.kill();
            let _ = child.wait();
            panic!("graceful termination exceeded deadline");
        }
        thread::sleep(Duration::from_millis(10));
    }
    let output = child.wait_with_output().unwrap();
    assert!(shutdown_started.elapsed() < Duration::from_secs(2));
    assert!(output.status.success() || incomplete_headers);
    let logs = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(logs.contains("draining native Roll requests"));
    for secret in [
        "private-password",
        "private-jwt-secret",
        "private-query-secret",
        "private-header-secret",
    ] {
        assert!(!logs.contains(secret));
    }
}

"""OpenCode launcher for starting opencode in background with health checks."""

import logging
import os
import random
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

LOG_FILE = Path("opencode.log")
PID_FILE = Path(".opencode.pid")

DEFAULT_PORTS = [4096, 4097, 4098, 4099, 4100]
MAX_RETRIES = 5
HEALTH_CHECK_INTERVAL = 2


def find_available_port(ports: list[int] | None = None) -> int:
    """Find an available port for opencode.

    Args:
        ports: List of ports to try (default: DEFAULT_PORTS)

    Returns:
        First available port
    """
    ports_to_try = ports or DEFAULT_PORTS

    for port in ports_to_try:
        try:
            result = subprocess.run(
                ["ss", "-tln"],
                capture_output=True,
                text=True,
                check=True,
            )
            port_in_use = False
            for line in result.stdout.split("\n"):
                if f":{port}" in line and "LISTEN" in line:
                    port_in_use = True
                    break

            if not port_in_use:
                logger.info(f"Found available port: {port}")
                return port
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    logger.warning("Could not find available port, using default: 4096")
    return 4096


def find_opencode_port() -> int | None:
    """Find which port opencode is listening on by checking default ports.

    Returns:
        Port number if found, None otherwise
    """
    for port in DEFAULT_PORTS:
        base_url = f"http://127.0.0.1:{port}"
        if check_health(base_url, timeout=2):
            logger.info(f"Found opencode healthy on port {port}")
            return port
    return None


def check_health(base_url: str, timeout: int = 5) -> bool:
    """Check if opencode is healthy.

    Args:
        base_url: Base URL of opencode server
        timeout: Request timeout in seconds

    Returns:
        True if healthy, False otherwise
    """
    try:
        response = requests.get(f"{base_url}/global/health", timeout=timeout)
        data = response.json()
        return data.get("healthy", False)
    except requests.RequestException as e:
        logger.debug(f"Health check failed: {e}")
        return False


def wait_for_healthy(base_url: str, max_wait: int = 30) -> bool:
    """Wait for opencode to become healthy.

    Args:
        base_url: Base URL of opencode server
        max_wait: Maximum time to wait in seconds

    Returns:
        True if healthy, False if timeout exceeded
    """
    logger.info(f"Waiting for opencode to be healthy at {base_url}...")

    start_time = time.time()
    elapsed = 0

    while elapsed < max_wait:
        if check_health(base_url):
            logger.info(f"opencode is healthy after {elapsed:.1f}s")
            return True

        time.sleep(HEALTH_CHECK_INTERVAL)
        elapsed = time.time() - start_time

    logger.error(f"opencode did not become healthy after {max_wait}s")
    return False


def is_opencode_running(base_url: str) -> bool:
    """Check if opencode is already running.

    Args:
        base_url: Base URL of opencode server

    Returns:
        True if running, False otherwise
    """
    port = find_opencode_port()
    if port:
        logger.info(f"Found opencode running on port {port}")
        return True
    return False


def kill_existing_opencode() -> None:
    """Kill existing opencode process if running."""
    if PID_FILE.exists():
        try:
            with open(PID_FILE) as f:
                pid = int(f.read().strip())

            try:
                os.kill(pid, 0)
                logger.info(f"Killing existing opencode process (PID: {pid})")
                os.kill(pid, signal.SIGTERM)
                time.sleep(2)

                try:
                    os.kill(pid, 0)
                    logger.warning("Process still running, sending SIGKILL")
                    os.kill(pid, signal.SIGKILL)
                    time.sleep(1)
                except OSError:
                    pass
            except OSError:
                logger.debug(f"Process {pid} not running")
        except (ValueError, OSError) as e:
            logger.warning(f"Failed to kill existing opencode: {e}")


def launch_opencode(
    base_url: str = "http://127.0.0.1:4096",
    log_file: Path = LOG_FILE,
    max_retries: int = MAX_RETRIES,
) -> bool:
    """Launch opencode in background with health checks.

    Args:
        base_url: Base URL for opencode server
        log_file: Path to log file
        max_retries: Maximum number of launch retries

    Returns:
        True if launch successful, False otherwise
    """
    logger.info(f"Launching opencode at {base_url}")

    if is_opencode_running(base_url):
        logger.info(f"opencode is already running at {base_url}")
        return True

    port = int(base_url.split(":")[-1])

    for attempt in range(max_retries):
        logger.info(f"Launch attempt {attempt + 1}/{max_retries}")

        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)

            process = subprocess.Popen(
                ["opencode", "run", "--port", str(port)],
                stdout=log_file.open("a"),
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,
            )

            with open(PID_FILE, "w") as f:
                f.write(str(process.pid))

            logger.info(f"Started opencode (PID: {process.pid})")

            if wait_for_healthy(base_url):
                logger.info(f"opencode launched successfully at {base_url}")
                return True
            else:
                logger.warning("opencode did not become healthy")
                process.terminate()
                time.sleep(1)

        except FileNotFoundError:
            logger.error("opencode command not found. Is it installed and in PATH?")
            return False
        except Exception as e:
            logger.error(f"Failed to launch opencode: {e}")

        backoff = 2**attempt + random.random()
        logger.info(f"Retrying in {backoff:.1f}s...")
        time.sleep(backoff)

    logger.error(f"Failed to launch opencode after {max_retries} attempts")
    return False


def ensure_opencode_running(
    base_url: str = "http://127.0.0.1:4096",
    restart: bool = False,
) -> tuple[bool, str]:
    """Ensure opencode is running, launching if necessary.

    Args:
        base_url: Base URL for opencode server
        restart: Whether to restart if already running

    Returns:
        (success, actual_url) tuple
    """
    port = find_opencode_port()
    if port:
        actual_url = f"http://127.0.0.1:{port}"
        logger.info(f"opencode already running at {actual_url}")
        if restart:
            logger.info("Restarting opencode...")
            kill_existing_opencode()
            return launch_opencode(base_url), base_url
        else:
            return True, actual_url

    logger.info("opencode not running, launching...")
    return launch_opencode(base_url), base_url


def stop_opencode() -> bool:
    """Stop opencode process.

    Returns:
        True if stopped, False if not running or error occurred
    """
    if not PID_FILE.exists():
        logger.info("No PID file found, opencode may not be running")
        return True

    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())

        try:
            os.kill(pid, 0)
            logger.info(f"Stopping opencode (PID: {pid})")
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            time.sleep(2)

            try:
                os.kill(pid, 0)
                logger.warning("Process still running, sending SIGKILL")
                os.killpg(os.getpgid(pid), signal.SIGKILL)
                time.sleep(1)
            except OSError:
                pass

            logger.info("opencode stopped")
            PID_FILE.unlink(missing_ok=True)
            return True
        except OSError:
            logger.debug(f"Process {pid} not running")
            PID_FILE.unlink(missing_ok=True)
            return True
    except (ValueError, OSError) as e:
        logger.warning(f"Failed to stop opencode: {e}")
        return False


def get_opencode_status() -> dict[str, Any]:
    """Get opencode status information.

    Returns:
        Dictionary with status information
    """
    status = {
        "running": False,
        "pid": None,
        "base_url": None,
        "healthy": False,
        "version": None,
    }

    for port in DEFAULT_PORTS:
        base_url = f"http://127.0.0.1:{port}"
        if check_health(base_url, timeout=2):
            status["running"] = True
            status["base_url"] = base_url
            status["healthy"] = True
            try:
                response = requests.get(f"{base_url}/global/health", timeout=2)
                data = response.json()
                status["version"] = data.get("version")
            except requests.RequestException:
                pass
            break

    if PID_FILE.exists():
        try:
            with open(PID_FILE) as f:
                pid = int(f.read().strip())

            try:
                os.kill(pid, 0)
                status["pid"] = pid
            except OSError:
                status["pid"] = None
        except (ValueError, OSError):
            pass

    return status

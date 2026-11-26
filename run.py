"""Start Anki Scribe and open it in the default browser."""

from __future__ import annotations

import logging
import socket
import threading
import time
import webbrowser

import httpx
import uvicorn

from app import __version__
from app.config import data_dir, data_fingerprint
from app.instance import InstanceLock
from app.logging_setup import configure_logging
from app.main import create_app

HOST = "127.0.0.1"
FIRST_PORT = 8777
PORT_SPAN = 30


def _url(port: int) -> str:
    return f"http://{HOST}:{port}"


def _health(port: int) -> dict | None:
    try:
        response = httpx.get(f"{_url(port)}/api/health", timeout=0.4)
        if response.status_code == 200:
            payload = response.json()
            return payload if isinstance(payload, dict) else None
    except Exception:
        return None
    return None


def _is_ours(port: int) -> bool:
    """Only an instance that serves *this* data folder counts as ours.

    A stray server left over from a test run, or a copy started with a different
    data folder, must never be adopted: it would show an empty library and the
    user would reasonably think their work was gone.
    """
    health = _health(port)
    return bool(
        health
        and health.get("app") == "anki-scribe"
        and health.get("data") == data_fingerprint()
    )


def _is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((HOST, port))
        except OSError:
            return False
    return True


def _find_running() -> int | None:
    """A previous instance may be on any port in the range, not just the first."""
    for port in range(FIRST_PORT, FIRST_PORT + PORT_SPAN):
        if _is_ours(port):
            return port
    return None


def _choose_port() -> tuple[int, bool]:
    running = _find_running()
    if running is not None:
        # Attach to the instance that is already open instead of starting a
        # second one on a different port: two processes share the same JSON
        # files and corrupt each other.
        return running, True
    for port in range(FIRST_PORT, FIRST_PORT + PORT_SPAN):
        if _is_free(port):
            return port, False
    raise RuntimeError(f"No free port between {FIRST_PORT} and {FIRST_PORT + PORT_SPAN}.")


def _open_when_ready(url: str) -> None:
    """Wait for the server to answer before opening the browser."""
    for _ in range(40):
        try:
            if httpx.get(f"{url}/api/health", timeout=0.3).status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.25)
    webbrowser.open(url)


def main() -> None:
    log_file = configure_logging(data_dir())
    logger = logging.getLogger("anki_scribe")

    # One instance per data folder: the lock is what protects the JSON files if
    # the port scan and the lock ever disagree.
    lock = InstanceLock(data_dir())
    holder = lock.acquire()
    if holder:
        port = int(holder.get("port") or 0)
        if port and _is_ours(port):
            url = _url(port)
            print(f"Anki Scribe is already running at {url}")
            logger.info("already running at %s", url)
            webbrowser.open(url)
            return
        print(
            "Anki Scribe is already running for this data folder "
            f"(pid {holder.get('pid')}). Run it again in a moment."
        )
        logger.info("instance lock held pid=%s port=%s", holder.get("pid"), port)
        return

    try:
        port, already_running = _choose_port()
        url = _url(port)

        if already_running:
            print(f"Anki Scribe is already running at {url}")
            logger.info("already running at %s", url)
            webbrowser.open(url)
            return

        lock.set_port(port)
        print()
        print("  Anki Scribe")
        print(f"  {url}")
        print("  Press Ctrl+C to stop.")
        print()

        logger.info("starting version=%s port=%s log=%s", __version__, port, log_file)
        threading.Thread(target=_open_when_ready, args=(url,), daemon=True).start()
        uvicorn.run(
            create_app(),
            host=HOST,
            port=port,
            log_level="info",
            access_log=False,
        )
    finally:
        lock.release()


if __name__ == "__main__":
    main()

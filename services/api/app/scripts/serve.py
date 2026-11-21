"""Dual-stack uvicorn entrypoint.

Why this exists:
    uvicorn's ``--host`` accepts a single string. If we pass ``::`` Python's
    asyncio explicitly sets ``IPV6_V6ONLY=1`` on the socket
    (see ``Lib/asyncio/base_events.py``), so the listener only accepts IPv6
    connections. On Fly.io we need both:

    * IPv6 — for 6PN private traffic (``aisoc-demo-api.internal:8000`` from
      sibling apps like the web Next.js rewriter), which routes via IPv6.
    * IPv4 — for ``fly-proxy``'s public health checks against
      ``api.tryaisoc.com/health``, which speak IPv4 to ``127.0.0.1:8000``.

    If we ``--host 0.0.0.0`` we lose 6PN reachability; if we ``--host ::``
    we lose the public health check (returns 503). The clean fix is to
    pre-bind a dual-stack socket with ``IPV6_V6ONLY=0`` and hand the file
    descriptor to uvicorn via ``--fd``.

This wrapper is the production CMD for the API container.
"""

from __future__ import annotations

import os
import socket
import sys


def worker_count(value: str | None) -> int:
    """How many API processes to run (pure): ACORN_API_WORKERS, 1 to 8, 1 when it is missing or not a number."""
    try:
        return max(1, min(8, int(value or "1")))
    except ValueError:
        return 1


def uvicorn_command(fd: int) -> list[str]:
    """The command of one API process that serves on the shared, already bound socket (pure)."""
    return [sys.executable, "-m", "uvicorn", "app.main:app", "--fd", str(fd)]


def supervise(cmd: list[str], workers: int, fd: int) -> None:
    """Run `workers` API processes on the one listening socket (the kernel hands each connection to one of them) so a slow request in one does not stall the others. A process that exits is started again;
    on SIGTERM or SIGINT every process is told to stop and this one waits for them. uvicorn's own --workers is not used: it binds its own socket and would drop the dual-stack listener above."""
    import signal
    import subprocess
    import time

    children: list[subprocess.Popen] = []
    stopping = False

    def start() -> subprocess.Popen:
        return subprocess.Popen(cmd, pass_fds=[fd])

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True
        for c in children:
            if c.poll() is None:
                c.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    children.extend(start() for _ in range(workers))
    last_restart = [0.0] * workers
    while not stopping:
        time.sleep(1)
        for i, c in enumerate(children):
            if c.poll() is not None and not stopping:
                if time.monotonic() - last_restart[i] < 5:
                    time.sleep(5)  # a process that dies at once is not started in a tight loop
                last_restart[i] = time.monotonic()
                children[i] = start()
    for c in children:
        try:
            c.wait(timeout=30)
        except subprocess.TimeoutExpired:
            c.kill()


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))

    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    # Allow IPv4-mapped IPv6 connections (dual-stack).
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("::", port))
    sock.listen(128)
    # Sockets created via socket.socket() in Python 3.4+ are non-inheritable
    # (close-on-exec). uvicorn re-opens the fd after exec, so we must mark
    # the descriptor as inheritable before handing off.
    os.set_inheritable(sock.fileno(), True)

    workers = worker_count(os.environ.get("ACORN_API_WORKERS"))
    cmd = uvicorn_command(sock.fileno())
    if workers == 1:
        os.execvp(cmd[0], cmd)  # the old behaviour: this process becomes uvicorn
    supervise(cmd, workers, sock.fileno())


if __name__ == "__main__":
    main()

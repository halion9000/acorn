"""The API entrypoint can run several processes on one listening socket (ACORN_API_WORKERS)."""

import os
import signal
import socket
import subprocess
import sys
import time

import pytest

from app.scripts import serve


def test_the_worker_count_is_one_to_eight_and_one_when_missing_or_not_a_number():
    assert [serve.worker_count(v) for v in (None, "", "3", "8", "20", "0", "-2", "many")] == [1, 1, 3, 8, 8, 1, 1, 1]


def test_each_process_serves_on_the_shared_socket_instead_of_binding_its_own():
    cmd = serve.uvicorn_command(7)
    assert cmd[1:] == ["-m", "uvicorn", "app.main:app", "--fd", "7"]
    assert "--workers" not in cmd  # uvicorn's own workers would bind a new socket and drop the dual-stack listener


CHILD = """
import os, socket, sys
srv = socket.fromfd(int(sys.argv[1]), socket.AF_INET6, socket.SOCK_STREAM)
while True:
    c, _ = srv.accept()
    c.sendall(str(os.getpid()).encode())
    c.close()
"""


@pytest.mark.skipif(sys.platform == "win32" or not hasattr(socket, "AF_INET6"), reason="passes an open socket to child processes: Linux (and macOS) only")
def test_three_processes_share_one_socket_a_killed_one_is_started_again_and_sigterm_stops_them(tmp_path):
    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    s.bind(("::", 0))
    s.listen(8)
    os.set_inheritable(s.fileno(), True)
    port = s.getsockname()[1]
    child = tmp_path / "child.py"
    child.write_text(CHILD)
    cmd = [sys.executable, str(child), str(s.fileno())]
    runner = f"import sys; sys.path.insert(0, {os.getcwd()!r}); from app.scripts import serve; serve.supervise({cmd!r}, 3, {s.fileno()})"
    sup = subprocess.Popen([sys.executable, "-c", runner], pass_fds=[s.fileno()])

    def pids(n):
        seen = set()
        for _ in range(n):
            with socket.create_connection(("::1", port), timeout=5) as c:
                seen.add(c.recv(20).decode())
        return seen

    try:
        time.sleep(2)
        first = pids(60)
        assert len(first) == 3
        victim = int(sorted(first)[0])
        os.kill(victim, signal.SIGKILL)
        time.sleep(8)
        again = pids(90)
        assert len(again) == 3 and str(victim) not in again
    finally:
        sup.send_signal(signal.SIGTERM)
        sup.wait(timeout=40)
        s.close()
    assert sup.returncode == 0

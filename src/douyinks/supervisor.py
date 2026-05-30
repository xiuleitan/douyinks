import logging
import subprocess
import sys
import time
from dataclasses import dataclass

from .config import Settings


logger = logging.getLogger("douyinks.supervisor")


@dataclass(frozen=True)
class ManagedProcess:
    name: str
    process: subprocess.Popen


def build_service_commands(settings: Settings, log_level: str = "INFO") -> list[tuple[str, list[str]]]:
    return [
        (
            "daemon",
            [
                sys.executable,
                "-m",
                "douyinks",
                "daemon",
                "--host",
                settings.daemon_host,
                "--port",
                str(settings.daemon_port),
            ],
        ),
        ("bot", [sys.executable, "-m", "douyinks", "bot", "--log-level", log_level]),
        (
            "sync-server",
            [
                sys.executable,
                "-m",
                "douyinks",
                "sync-server",
                "--host",
                settings.sync_server_host,
                "--port",
                str(settings.sync_server_port),
                "--log-level",
                log_level,
            ],
        ),
    ]


def supervise_services(commands: list[tuple[str, list[str]]]) -> None:
    processes = _start_processes(commands)
    try:
        while True:
            for item in processes:
                exit_code = item.process.poll()
                if exit_code is not None:
                    raise RuntimeError(f"{item.name} exited with code {exit_code}")
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Received interrupt, stopping services")
    finally:
        _stop_processes(processes)


def _start_processes(commands: list[tuple[str, list[str]]]) -> list[ManagedProcess]:
    processes: list[ManagedProcess] = []
    try:
        for name, command in commands:
            logger.info("Starting %s: %s", name, " ".join(command))
            processes.append(ManagedProcess(name=name, process=subprocess.Popen(command)))
    except Exception:
        _stop_processes(processes)
        raise
    return processes


def _stop_processes(processes: list[ManagedProcess]) -> None:
    for item in processes:
        if item.process.poll() is None:
            logger.info("Stopping %s", item.name)
            item.process.terminate()
    deadline = time.monotonic() + 10
    for item in processes:
        if item.process.poll() is not None:
            continue
        timeout = max(0.1, deadline - time.monotonic())
        try:
            item.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("Killing %s after graceful shutdown timeout", item.name)
            item.process.kill()
    for item in processes:
        if item.process.poll() is None:
            item.process.wait()

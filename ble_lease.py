from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Callable

PROTOCOL_VERSION = 1
PIPE_NAME = r"\\.\pipe\MagpieLcdBridge.BleLease.v1"
KEY_PATH = (
    Path(os.environ.get("LOCALAPPDATA", Path.home()))
    / "MagpieLcdBridge"
    / "ble-lease.key"
)
DEFAULT_TTL_SECONDS = 120
MIN_TTL_SECONDS = 30
MAX_TTL_SECONDS = 600
BLE_RELEASE_GRACE_SECONDS = 0.5
MAX_MESSAGE_BYTES = 64 * 1024

log = logging.getLogger("magpie-lcd-lease")


def normalize_ttl(value: object) -> int:
    try:
        ttl = int(value if value is not None else DEFAULT_TTL_SECONDS)
    except (TypeError, ValueError) as error:
        raise ValueError("租约有效期必须是整数秒") from error
    if not MIN_TTL_SECONDS <= ttl <= MAX_TTL_SECONDS:
        raise ValueError(
            f"租约有效期必须在 {MIN_TTL_SECONDS}-{MAX_TTL_SECONDS} 秒之间"
        )
    return ttl


@dataclass(frozen=True)
class Lease:
    owner: str
    token: str
    expires_at: float
    worker_was_running: bool


class BleLeaseManager:
    def __init__(
        self,
        worker,
        worker_lock: threading.RLock,
        *,
        interval_getter: Callable[[], int],
        clock: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] = lambda: secrets.token_hex(16),
        release_wait: float = BLE_RELEASE_GRACE_SECONDS,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.worker = worker
        self.worker_lock = worker_lock
        self.interval_getter = interval_getter
        self.clock = clock
        self.token_factory = token_factory
        self.release_wait = release_wait
        self.on_change = on_change
        self._lease: Lease | None = None
        self._lock = threading.RLock()

    @property
    def owner(self) -> str | None:
        with self._lock, self.worker_lock:
            self._expire_locked()
            return self._lease.owner if self._lease else None

    def acquire(self, owner: object, ttl_seconds: object) -> dict:
        owner_name = str(owner or "").strip()
        if not owner_name or len(owner_name) > 64:
            return {"ok": False, "state": "invalid_owner"}
        ttl = normalize_ttl(ttl_seconds)
        changed = False
        with self._lock, self.worker_lock:
            self._expire_locked()
            if self._lease is not None:
                remaining = max(0, int(self._lease.expires_at - self.clock()))
                return {
                    "ok": False,
                    "state": "busy",
                    "owner": self._lease.owner,
                    "expires_in": remaining,
                }
            worker_was_running = self.worker.is_running()
            if worker_was_running:
                self.worker.stop()
                if self.release_wait > 0:
                    time.sleep(self.release_wait)
            self._lease = Lease(
                owner=owner_name,
                token=self.token_factory(),
                expires_at=self.clock() + ttl,
                worker_was_running=worker_was_running,
            )
            changed = True
            response = {
                "ok": True,
                "state": "granted",
                "owner": owner_name,
                "token": self._lease.token,
                "expires_in": ttl,
                "worker_was_running": worker_was_running,
            }
        if changed and self.on_change:
            self.on_change()
        return response

    def heartbeat(self, token: object, ttl_seconds: object | None = None) -> dict:
        ttl = normalize_ttl(ttl_seconds)
        with self._lock:
            self._expire_locked()
            if self._lease is None:
                return {"ok": False, "state": "expired"}
            if not secrets.compare_digest(self._lease.token, str(token or "")):
                return {"ok": False, "state": "invalid_token"}
            self._lease = Lease(
                owner=self._lease.owner,
                token=self._lease.token,
                expires_at=self.clock() + ttl,
                worker_was_running=self._lease.worker_was_running,
            )
            return {
                "ok": True,
                "state": "granted",
                "owner": self._lease.owner,
                "expires_in": ttl,
            }

    def release(self, token: object) -> dict:
        changed = False
        with self._lock, self.worker_lock:
            self._expire_locked()
            if self._lease is None:
                return {"ok": False, "state": "expired"}
            if not secrets.compare_digest(self._lease.token, str(token or "")):
                return {"ok": False, "state": "invalid_token"}
            worker_resumed = self._resume_worker_locked()
            self._lease = None
            changed = True
            response = {
                "ok": True,
                "state": "released",
                "worker_resumed": worker_resumed,
            }
        if changed and self.on_change:
            self.on_change()
        return response

    def status(self) -> dict:
        with self._lock, self.worker_lock:
            self._expire_locked()
            lease = None
            if self._lease is not None:
                lease = {
                    "owner": self._lease.owner,
                    "expires_in": max(0, int(self._lease.expires_at - self.clock())),
                }
            return {
                "ok": True,
                "state": "active" if lease else "idle",
                "lease": lease,
                "worker_running": self.worker.is_running(),
            }

    def start_worker_if_idle(self, interval: int) -> str | None:
        with self._lock, self.worker_lock:
            self._expire_locked()
            if self._lease is not None:
                return self._lease.owner
            self.worker.start(interval)
            return None

    def restart_worker_if_idle(self, interval: int) -> str | None:
        with self._lock, self.worker_lock:
            self._expire_locked()
            if self._lease is not None:
                return self._lease.owner
            self.worker.restart(interval)
            return None

    def expire_if_needed(self) -> bool:
        changed = False
        with self._lock, self.worker_lock:
            changed = self._expire_locked()
        if changed and self.on_change:
            self.on_change()
        return changed

    def _expire_locked(self) -> bool:
        if self._lease is None or self.clock() < self._lease.expires_at:
            return False
        expired = self._lease
        self._resume_worker_locked()
        self._lease = None
        log.info("BLE 租约已超时：owner=%s", expired.owner)
        return True

    def _resume_worker_locked(self) -> bool:
        if not self._lease or not self._lease.worker_was_running:
            return False
        if self.worker.is_running():
            return False
        self.worker.start(self.interval_getter())
        return True


def request_lease(
    payload: dict,
    *,
    pipe_name: str = PIPE_NAME,
    key_path: Path = KEY_PATH,
) -> dict:
    request = {"protocol": PROTOCOL_VERSION, **payload}
    key = key_path.read_bytes()
    with Client(pipe_name, family="AF_PIPE", authkey=key) as connection:
        connection.send_bytes(json.dumps(request, ensure_ascii=False).encode("utf-8"))
        raw = connection.recv_bytes(MAX_MESSAGE_BYTES)
    response = json.loads(raw.decode("utf-8"))
    if not isinstance(response, dict):
        raise RuntimeError("BLE 租约响应格式无效")
    return response


class BleLeasePipeServer:
    def __init__(
        self,
        manager: BleLeaseManager,
        *,
        pipe_name: str = PIPE_NAME,
        key_path: Path = KEY_PATH,
    ) -> None:
        self.manager = manager
        self.pipe_name = pipe_name
        self.key_path = key_path
        self.listener: Listener | None = None
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.authkey: bytes | None = None

    def start(self) -> None:
        if self.thread is not None:
            return
        self.authkey = secrets.token_bytes(32)
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path.write_bytes(self.authkey)
        self.listener = Listener(
            self.pipe_name,
            family="AF_PIPE",
            authkey=self.authkey,
        )
        self.thread = threading.Thread(
            target=self._serve,
            name="magpie-lcd-ble-lease",
            daemon=True,
        )
        self.thread.start()
        log.info("BLE 租约服务已启动")

    def stop(self) -> None:
        if self.thread is None:
            return
        self.stop_event.set()
        try:
            if self.key_path.exists():
                request_lease(
                    {"op": "status"},
                    pipe_name=self.pipe_name,
                    key_path=self.key_path,
                )
        except Exception:
            pass
        self.thread.join(timeout=3)
        if self.listener is not None:
            try:
                self.listener.close()
            except Exception:
                pass
        self.listener = None
        self.thread = None
        self.key_path.unlink(missing_ok=True)
        self.authkey = None
        log.info("BLE 租约服务已停止")

    def _serve(self) -> None:
        assert self.listener is not None
        while True:
            try:
                connection = self.listener.accept()
            except AuthenticationError:
                log.warning("BLE 租约认证失败，继续接受请求")
                continue
            try:
                raw = connection.recv_bytes(MAX_MESSAGE_BYTES)
                response = self._handle(raw)
                connection.send_bytes(
                    json.dumps(response, ensure_ascii=False).encode("utf-8")
                )
            except Exception as error:
                log.warning("BLE 租约请求失败：%s: %r", type(error).__name__, error)
                try:
                    connection.send_bytes(
                        json.dumps(
                            {"ok": False, "state": "error"},
                            ensure_ascii=False,
                        ).encode("utf-8")
                    )
                except Exception:
                    pass
            finally:
                connection.close()
            if self.stop_event.is_set():
                return

    def _handle(self, raw: bytes) -> dict:
        request = json.loads(raw.decode("utf-8"))
        if not isinstance(request, dict):
            return {"ok": False, "state": "invalid_request"}
        if request.get("protocol") != PROTOCOL_VERSION:
            return {"ok": False, "state": "unsupported_protocol"}
        operation = request.get("op")
        if operation == "status":
            return self.manager.status()
        if operation == "acquire":
            return self.manager.acquire(
                request.get("owner"),
                request.get("ttl_seconds", DEFAULT_TTL_SECONDS),
            )
        if operation == "heartbeat":
            return self.manager.heartbeat(
                request.get("token"),
                request.get("ttl_seconds", DEFAULT_TTL_SECONDS),
            )
        if operation == "release":
            return self.manager.release(request.get("token"))
        return {"ok": False, "state": "unknown_operation"}


class LeaseWatchdog:
    def __init__(self, manager: BleLeaseManager, interval: float = 1.0) -> None:
        self.manager = manager
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self._run,
            name="magpie-lcd-ble-lease-watchdog",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2)

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            try:
                self.manager.expire_if_needed()
            except Exception:
                log.exception("BLE 租约超时检查失败")

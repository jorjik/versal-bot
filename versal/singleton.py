from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def _pid_alive(pid: int) -> bool:
    """Жив ли процесс с данным pid (без psutil; работает на Windows и Linux)."""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",  # Windows-кодировка вывода tasklist
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return str(pid) in result.stdout
        except Exception:
            return True  # не смогли проверить — считаем процесс живым
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_lock(lock_path: Path) -> bool:
    """Захватывает singleton-лок (pid-файл).

    Возвращает False, если бот уже запущен. Мёртвые (stale) лока
    автоматически подчищаются.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    for _ in range(3):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if _lock_owner_alive(lock_path):
                return False
            try:
                lock_path.unlink()
            except OSError:
                return False
            continue  # stale-лок удалён, пробуем создать заново

        try:
            os.write(fd, str(os.getpid()).encode())
        finally:
            os.close(fd)
        return True

    return False


def _lock_owner_alive(lock_path: Path) -> bool:
    """True, если pid-файл принадлежит живому процессу.

    Пустой/нечитаемый файл (владелец ещё не записал pid) считаем живым
    и даём ему пару мгновений — иначе можно удалить чужой свежий лок.
    """
    for _ in range(3):
        try:
            pid = int(lock_path.read_text().strip())
            return _pid_alive(pid)
        except ValueError:
            time.sleep(0.2)
        except OSError:
            return True
    return False


def release_lock(lock_path: Path) -> None:
    """Снимает лок, только если он наш."""
    try:
        if lock_path.exists() and lock_path.read_text().strip() == str(os.getpid()):
            lock_path.unlink()
    except OSError:
        pass

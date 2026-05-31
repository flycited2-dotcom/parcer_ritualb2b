"""Обёртка над systemctl/journalctl для управления юнитами парсера."""
import asyncio
import os
import shlex

PARSER_UNIT = os.getenv("PARSER_UNIT", "ritual_parser.service")
PARSER_TIMER = os.getenv("PARSER_TIMER", "ritual_parser.timer")
EMAILS_UNIT = os.getenv("EMAILS_UNIT", "ritual_email_finder.service")


async def _run(*args: str, timeout: float = 30.0) -> tuple[int, str]:
    """Выполнить команду, вернуть (returncode, combined_stdout_stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, f"timeout after {timeout}s: {' '.join(shlex.quote(a) for a in args)}"
    return proc.returncode, (out or b"").decode("utf-8", errors="replace")


async def systemctl(action: str, unit: str) -> tuple[int, str]:
    # `systemctl start` для oneshot-юнита блокируется до конца прогона (часы).
    # --no-block возвращает управление сразу — иначе ловим timeout rc=124.
    args = ["sudo", "-n", "systemctl", action, unit]
    if action in ("start", "restart", "stop"):
        args.append("--no-block")
    return await _run(*args)


async def is_active(unit: str) -> bool:
    code, out = await _run("systemctl", "is-active", unit)
    return out.strip() == "active"


async def status_oneline(unit: str) -> str:
    """Краткий вывод is-active + ActiveEnterTimestamp."""
    _, out = await _run("systemctl", "show", unit,
                         "--property=ActiveState,SubState,ActiveEnterTimestamp")
    return out.strip()


async def journal_tail(unit: str, n: int = 50) -> str:
    code, out = await _run("journalctl", "-u", unit, "-n", str(n), "--no-pager",
                           timeout=20)
    return out


async def health() -> str:
    """uptime + df / + free -m в одной строке."""
    parts = []
    for cmd in (("uptime",), ("df", "-h", "/"), ("free", "-m")):
        _, out = await _run(*cmd, timeout=10)
        parts.append(f"$ {' '.join(cmd)}\n{out.strip()}")
    return "\n\n".join(parts)

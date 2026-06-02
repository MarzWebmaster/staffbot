#!/usr/bin/env python3
"""
StaffBot.my — Sandbox Agent (runs inside each client container).
=================================================================
NO AI logic. NO LLM calls. Hermes Gateway handles all reasoning.
This container is a secure execution sandbox — it receives tool
commands from Gateway and returns output.

Endpoints:
  GET  /health              — Container health check
  POST /exec                — Execute a shell command (sandboxed)
  POST /exec/python         — Execute Python code (sandboxed)
  GET  /memory/usage        — Disk/memory usage stats

Security:
  - All commands run in isolated subprocess
  - Timeout enforced per command (max 60s)
  - Output capped at 100KB
  - No network access to other containers
  - Runs as non-root hermes user
"""

import asyncio
import os
import resource
import subprocess
import sys
import tempfile
import time
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="StaffBot Sandbox Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

CLIENT_ID = os.environ.get("CLIENT_ID", "0")
SUBDOMAIN = os.environ.get("SUBDOMAIN", "")
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://staffbot-hermes-gateway:8080")

MAX_CMD_TIMEOUT = int(os.environ.get("MAX_CMD_TIMEOUT", "60"))
MAX_OUTPUT_BYTES = int(os.environ.get("MAX_OUTPUT_BYTES", "102400"))  # 100KB


class ExecRequest(BaseModel):
    command: str
    cwd: Optional[str] = "/app/data/workspace"
    timeout: Optional[int] = 30


class ExecResponse(BaseModel):
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float


def _limit_resources():
    """Set resource limits for subprocess."""
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (MAX_CMD_TIMEOUT, MAX_CMD_TIMEOUT))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))  # 512MB
    except Exception:
        pass


@app.get("/health")
async def health():
    """Health check for Gateway verification."""
    return {
        "status": "ok",
        "client_id": CLIENT_ID,
        "subdomain": SUBDOMAIN,
        "type": "staffbot-sandbox",
    }


@app.post("/exec", response_model=ExecResponse)
async def exec_command(req: ExecRequest):
    """Execute a shell command in a sandboxed subprocess."""
    timeout = min(req.timeout or 30, MAX_CMD_TIMEOUT)
    cwd = req.cwd or "/app/data/workspace"

    # Ensure cwd exists
    os.makedirs(cwd, exist_ok=True)

    start = time.monotonic()

    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_shell(
                req.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                preexec_fn=_limit_resources,
            ),
            timeout=timeout,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            stdout_bytes, stderr_bytes = await proc.communicate()

        stdout = stdout_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
        stderr = stderr_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]

        return ExecResponse(
            success=(proc.returncode == 0),
            exit_code=proc.returncode or -1,
            stdout=stdout,
            stderr=stderr,
            duration_ms=(time.monotonic() - start) * 1000,
        )

    except asyncio.TimeoutError:
        return ExecResponse(
            success=False,
            exit_code=-1,
            stdout="",
            stderr=f"Command timed out after {timeout}s",
            duration_ms=timeout * 1000,
        )


@app.post("/exec/python", response_model=ExecResponse)
async def exec_python(req: ExecRequest):
    """Execute Python code in a temp file safely."""
    timeout = min(req.timeout or 30, MAX_CMD_TIMEOUT)

    # Write code to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        # Add safety preamble
        f.write("""\
import sys, os
sys.path.insert(0, '/app/data/workspace')
os.chdir('/app/data/workspace')
""")
        f.write(req.command)
        tmp_path = f.name

    start = time.monotonic()

    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                sys.executable, tmp_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=_limit_resources,
            ),
            timeout=timeout,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            stdout_bytes, stderr_bytes = await proc.communicate()

        stdout = stdout_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
        stderr = stderr_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]

        return ExecResponse(
            success=(proc.returncode == 0),
            exit_code=proc.returncode or -1,
            stdout=stdout,
            stderr=stderr,
            duration_ms=(time.monotonic() - start) * 1000,
        )

    except asyncio.TimeoutError:
        return ExecResponse(
            success=False,
            exit_code=-1,
            stdout="",
            stderr=f"Python execution timed out after {timeout}s",
            duration_ms=timeout * 1000,
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@app.get("/memory/usage")
async def memory_usage():
    """Report disk/memory usage for this container."""
    try:
        # Disk usage of data directory
        data_dir = "/app/data"
        if os.path.exists(data_dir):
            du = subprocess.check_output(
                ["du", "-sh", data_dir],
                stderr=subprocess.DEVNULL,
                timeout=10,
            ).decode().split()[0]
        else:
            du = "N/A"
    except Exception:
        du = "unknown"

    return {
        "disk_usage": du,
        "client_id": CLIENT_ID,
    }

"""SSH connection settings and portable quoting; no passwords are stored by the app."""
import base64
from dataclasses import dataclass
import os
import re
import shlex
import subprocess


@dataclass(frozen=True)
class SSHConnection:
    host: str
    directory: str
    python: str
    platform: str = "windows"

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@:\[\]-]*", self.host):
            raise ValueError("Set MECHANICAL_SSH_HOST to an SSH alias or username@hostname.")
        if not self.directory or not self.python:
            raise ValueError("Set the remote project directory and remote Python executable.")
        if self.platform not in ("windows", "posix"):
            raise ValueError("MECHANICAL_REMOTE_PLATFORM must be windows or posix.")
        if any("\x00" in s or "\n" in s or "\r" in s for s in (self.directory, self.python)):
            raise ValueError("Remote paths must be single-line paths.")
        if self.platform == "windows" and not re.match(r"^[A-Za-z]:[/\\]", self.directory):
            raise ValueError("Use an absolute Windows path for MECHANICAL_REMOTE_DIR.")
        if self.platform == "posix" and not self.directory.startswith("/"):
            raise ValueError("Use an absolute path for MECHANICAL_REMOTE_DIR.")

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("MECHANICAL_SSH_HOST", ""), os.environ.get("MECHANICAL_REMOTE_DIR", ""),
                   os.environ.get("MECHANICAL_REMOTE_PYTHON", ""), os.environ.get("MECHANICAL_REMOTE_PLATFORM", "windows"))

    def python_command(self, arguments):
        words = [self.python, *arguments]
        if self.platform == "windows":
            script = "$ErrorActionPreference='Stop'; & " + " ".join("'" + w.replace("'", "''") + "'" for w in words)
            script += "; exit $LASTEXITCODE"
            encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
            remote = "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + encoded
        else:
            remote = shlex.join(words)
        return ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=yes",
                "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3", self.host, remote]

    def command(self, action, job_id=None):
        script = self.directory.rstrip("/\\") + "/scripts/ssh-worker.py"
        arguments = [script, action]
        if job_id:
            arguments += ["--job-id", job_id]
        return self.python_command(arguments)

    def check(self):
        import json
        try:
            result = subprocess.run(self.command("check"), capture_output=True, timeout=25)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("SSH connection timed out. Check Tailscale and remote SSH access.") from exc
        if result.returncode:
            raise ValueError("SSH worker check failed: " + result.stderr.decode(errors="replace")[-2000:])
        info = json.loads(result.stdout)
        if info.get("service") != "project2-mechanical-ssh" or info.get("protocolVersion") != 1:
            raise ValueError("The remote worker returned an incompatible response.")
        return info

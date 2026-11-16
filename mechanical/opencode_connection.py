"""Authenticated file transfer and fixed worker commands through OpenCode v2.

Uses the shell API directly. No browser, SSH, or AI chat session is involved.
"""
import base64
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import time
import urllib.error
import urllib.parse
import urllib.request

from .contract import write_json
from .transfer import MAX_RESULTS

ROOT = Path(__file__).resolve().parent.parent


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None  # Never forward the login to another address.


class OpenCodeAPI:
    def __init__(self, config_path=None, location=None):
        path = Path(config_path or os.environ.get("OPENCODE_CONFIG", ROOT / ".env.opencode.json"))
        try:
            config = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise ValueError("Configure the remote webpage login in .env.opencode.json.") from exc
        self.url = str(config.get("url", "")).rstrip("/")
        parsed = urllib.parse.urlsplit(self.url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path):
            raise ValueError("OpenCode URL must be a server address without a login or path.")
        username, password = config.get("username", ""), config.get("password", "")
        if not username or not password or ":" in username:
            raise ValueError("Fill in the remote webpage username and password in .env.opencode.json.")
        self._authorization = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
        self.location = location
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def open(self, path, body=None, query=None, binary=False, timeout=30):
        params = dict(query or {})
        if self.location:
            params["location[directory]"] = self.location
        url = self.url + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Authorization": self._authorization}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/octet-stream" if binary else "application/json"
            data = body if binary else json.dumps(body).encode()
        try:
            return self._opener.open(urllib.request.Request(url, data=data, headers=headers), timeout=timeout)
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            if code in (401, 403):
                raise ValueError("The remote portal rejected the login or access to this API.") from None
            raise ValueError(f"OpenCode API {path} returned HTTP {code}.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ValueError("Cannot reach the OpenCode API. Check Tailscale and the remote server.") from None

    def json(self, path, body=None, query=None):
        with self.open(path, body, query) as response:
            if "application/json" not in response.headers.get("Content-Type", ""):
                raise ValueError("The remote server did not return the expected OpenCode API response.")
            return json.load(response)

    def write_file(self, path, data):
        with self.open("/api/experimental/fs/write", data, {"path": path}, binary=True, timeout=120) as response:
            return json.load(response)

    def read_file(self, path, destination=None, max_bytes=MAX_RESULTS):
        relative = PurePosixPath(path)
        if relative.is_absolute() or ".." in relative.parts or "\\" in path or ":" in path:
            raise ValueError("Downloads must stay inside the remote worker directory.")
        endpoint = "/api/fs/read/" + urllib.parse.quote(path, safe="/")
        with self.open(endpoint, timeout=120) as response:
            if destination is None:
                data = response.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise ValueError("Remote file exceeds the transfer limit.")
                return data
            destination = Path(destination)
            temporary = destination.with_suffix(destination.suffix + ".part")
            try:
                count = 0
                with temporary.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        count += len(chunk)
                        if count > max_bytes:
                            raise ValueError("Remote file exceeds the transfer limit.")
                        output.write(chunk)
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
            return destination

    def start_shell(self, command, timeout_seconds):
        return self.json("/api/shell", {"command": command, "cwd": self.location,
                                      "timeout": int(timeout_seconds * 1000),
                                      "metadata": {"project": "Project2-24679"}})["data"]

    def shell_info(self, shell_id):
        return self.json("/api/shell/" + urllib.parse.quote(shell_id, safe=""))["data"]

    def shell_output(self, shell_id):
        return self.json("/api/shell/" + urllib.parse.quote(shell_id, safe="") + "/output",
                         query={"limit": 100000})["data"]["output"]

    def wait_shell(self, info, timeout_seconds):
        deadline = time.monotonic() + timeout_seconds
        transient_failures = 0
        while info["status"] == "running":
            if time.monotonic() >= deadline:
                raise TimeoutError("Stopped waiting; the remote command may still be running.")
            time.sleep(1)
            try:
                info = self.shell_info(info["id"])
                transient_failures = 0
            except ValueError as exc:
                transient_failures += 1
                transient = 'Cannot reach' in str(exc) or any('HTTP ' + n in str(exc) for n in ('502', '503', '504'))
                if not transient or transient_failures >= 3:
                    raise
                # Only repeat this read of the known shell ID, never the submission.
                time.sleep(2)
        if info["status"] != "exited" or info.get("exit") != 0:
            raise ValueError("Remote worker command failed: " + self.shell_output(info["id"])[-4000:])
        return info


class OpenCodeConnection:
    transport = "opencode"
    platform = "windows"

    def __init__(self, directory, python, config_path=None, expected_url=None):
        for value in (directory, python):
            if not PureWindowsPath(value).is_absolute() or any(c in value for c in "\n\r\x00"):
                raise ValueError("Configure absolute Windows paths for the remote worker and Python.")
        self.directory, self.python = directory, python
        self.api = OpenCodeAPI(config_path, location=directory)
        if expected_url and self.api.url != expected_url:
            raise ValueError("This job belongs to a different OpenCode server; use its original configuration.")
        self.host = self.api.url

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("MECHANICAL_REMOTE_DIR", ""), os.environ.get("MECHANICAL_REMOTE_PYTHON", ""))

    def python_command(self, arguments):
        quote = lambda word: "'" + str(word).replace("'", "''") + "'"
        script = "$ErrorActionPreference='Stop'; & " + " ".join(quote(word) for word in [self.python, *arguments])
        script += "; exit $LASTEXITCODE"
        return "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + base64.b64encode(script.encode("utf-16le")).decode()

    def command(self, action, job_id=None, extra=()):
        arguments = [str(PureWindowsPath(self.directory) / "scripts/api-worker.py"), action]
        if job_id:
            arguments += ["--job-id", job_id]
        return self.python_command([*arguments, *extra])

    def check(self):
        info = self.api.start_shell(self.command("check"), 25)
        self.api.wait_shell(info, 30)
        result = json.loads(self.api.shell_output(info["id"]))
        if result.get("service") != "project2-mechanical-ssh" or result.get("protocolVersion") != 1:
            raise ValueError("The remote worker returned an incompatible response.")
        return result

    def run(self, data, record_path, timeout_seconds=1050):
        record_path = Path(record_path)
        record = json.loads(record_path.read_text())
        job_id = record["jobId"]
        try:
            input_path = f"uploads/{job_id}.zip"
            self.api.write_file(input_path, data)
            info = self.api.start_shell(self.command("run-file", job_id,
                                        ["--input-file", str(PureWindowsPath(self.directory) / input_path)]), 960)
            record["shellId"] = info["id"]
            write_json(record_path, record)
            self.api.wait_shell(info, timeout_seconds)
            return self.fetch(job_id, record_path.parent)
        except (ValueError, TimeoutError, OSError) as exc:
            raise ValueError(f"Remote job {job_id}: {exc} The job record is saved locally. "
                             "Check it with scripts/remote-job.py before submitting again; it may still be running.") from exc

    def fetch(self, job_id, directory):
        return self.api.read_file(f"worker-data/{job_id}/simulation.zip", Path(directory) / "simulation.zip")

    def status(self, record):
        missing_shell = False
        if record.get("shellId"):
            try:
                shell = self.api.shell_info(record["shellId"])
            except ValueError as exc:
                # Shell handles can disappear while the detached worker remains
                # alive. A missing handle is NOT proof that no job was submitted.
                expected = f"OpenCode API /api/shell/{record['shellId']} returned HTTP 404."
                if str(exc) != expected:
                    raise
                missing_shell = True
            else:
                if shell["status"] == "running":
                    return {"jobId": record["jobId"], "status": "running"}
                if shell["status"] != "exited" or shell.get("exit") != 0:
                    return {"jobId": record["jobId"], "status": "interrupted", "shellStatus": shell["status"],
                            "output": self.api.shell_output(record["shellId"])[-4000:]}
        status = json.loads(self.api.read_file(f"worker-data/{record['jobId']}/status.json", max_bytes=4 * 1024 * 1024))
        if any(not record.get(key) or status.get(key) != record[key]
               for key in ('jobId','modelId','submissionSHA256')):
            raise ValueError('The worker status does not match the original job identity; do not resubmit.')
        if missing_shell:
            status['shellHandleMissing'] = True
        return status

"""Run the installed wheel outside its checkout, including the real local web server."""

import argparse
import json
import os
import re
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", type=Path, required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--archive", type=Path, required=True)
    args = ap.parse_args()
    with zipfile.ZipFile(args.archive) as archive:
        prefix = f"decompnet-{args.version}/"
        command = archive.read(prefix + "windows.cmd")
        assert b"\r\n" in command and b"\n" not in command.replace(b"\r\n", b""), "Windows launcher needs CRLF"
        assert archive.read(prefix + "site/public/install.ps1")
        assert archive.read(prefix + "native/n64/n64.cpp")
    with tempfile.TemporaryDirectory(prefix="decomp-release-") as temporary:
        work = Path(temporary)
        environment = {**os.environ, "DECOMP_HOME": str(work / "home"), "DECOMP_UPDATES": "off", "DECOMP_RUNTIME": "native"}
        # Preserve the virtualenv executable: resolving its symlink runs base Python.
        python = str(args.python.absolute())
        code = ("import decompnet; from decompnet.rom import n64; "
                f"assert decompnet.__version__ == {args.version!r}; "
                "assert n64.to_z64(bytes.fromhex('80371240'))[1] == 'z64'; "
                "from decompnet.app import cli; from decompnet import toolchains; "
                "assert toolchains.current_platform() in ('windows-x86_64','linux-x86_64'); print('installed package and native analyzer OK')")
        subprocess.run([python, "-I", "-c", code], cwd=work, env=environment, check=True, timeout=30)
        for module in ("decompnet.cli", "decompnet.app.cli"):
            subprocess.run([python, "-I", "-m", module, "--help"], cwd=work, env=environment,
                           check=True, capture_output=True, timeout=30)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        address = f"http://127.0.0.1:{port}"
        process = subprocess.Popen([python, "-I", "-m", "decompnet.app.cli", "--no-browser", "--port", str(port)],
                                   cwd=work, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("installed application exited before becoming healthy")
                try:
                    with urllib.request.urlopen(address + "/health", timeout=1) as response:
                        health = json.load(response)
                    break
                except (OSError, ValueError):
                    time.sleep(0.1)
            else:
                raise RuntimeError("installed web application did not become healthy")
            assert health["app"] == "decomp-wtf" and health["version"] == args.version
            session = json.loads((work / "home/.decomp/server.json").read_text(encoding="utf-8"))
            headers = {"Cookie": "decomp_live=" + session["secret"], "X-Decomp": "1"}
            for endpoint in ("/", "/api/state", "/api/projects"):
                with urllib.request.urlopen(urllib.request.Request(address + endpoint, headers=headers), timeout=10) as response:
                    assert response.status == 200
                    response.read()
            request = urllib.request.Request(address + "/api/quit", headers=headers, data=b"{}", method="POST")
            with urllib.request.urlopen(request, timeout=10) as response:
                assert response.status == 200
            process.wait(timeout=20)
            assert process.returncode == 0
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                log = process.communicate(timeout=10)[0].decode("utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                process.kill()
                log = process.communicate()[0].decode("utf-8", errors="replace")
            if process.returncode:
                print(re.sub(r"([?&]k=)[A-Za-z0-9_-]+", r"\1<redacted>", log)[-5000:])
        print(json.dumps({"version": args.version, "installed_native_analyzer": True, "cli": True,
                          "web_health": True, "authenticated_api": True, "shutdown": True, "source_zip": True}))


if __name__ == "__main__":
    main()

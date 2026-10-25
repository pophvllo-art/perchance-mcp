"""The MCP SDK rejects any Host header that is not localhost. Behind a public
domain and a reverse proxy that means every request fails with
"Invalid Host header" (421). These tests prove the deployment works.

Run standalone:  python tests/test_host_header.py
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOSTNAME = "perchance-mcp-grhufy2l-lune-tester.cloady.io"
KEY = "test-secret-key-123"


def boot(port, extra_env):
    env = dict(os.environ)
    env.update({
        "PERCHANCE_API_KEY": KEY,
        "PERCHANCE_IMAGE_DIR": "/tmp/perchance-host-tests",
        "PORT": str(port),
        "PERCHANCE_READY_TIMEOUT": "5",
    })
    env.update(extra_env)
    proc = subprocess.Popen([sys.executable, "-m", "app.main"], env=env, cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3)
            return proc
        except Exception:
            time.sleep(0.5)
    return proc


def mcp_init(port, host_header):
    payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                          "clientInfo": {"name": "t", "version": "1"}}}
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream",
               "Authorization": f"Bearer {KEY}",
               "Host": host_header}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/mcp",
                                 data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    try:
        return urllib.request.urlopen(req, timeout=20).status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception as exc:  # noqa: BLE001
        return repr(exc)[:60]


def check(port, env, host, expected, label):
    proc = boot(port, env)
    try:
        got = mcp_init(port, host)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
    status = "PASS" if got == expected else "FAIL"
    print(f"  [{status}] {label}: got {got}, want {expected}")
    return got == expected


def main():
    results = []
    env = {"PUBLIC_URL": f"https://{HOSTNAME}"}
    results.append(check(8201, env, HOSTNAME, 200, "public host accepted"))
    results.append(check(8202, env, f"{HOSTNAME}:8443", 200, "public host with a port"))
    results.append(check(8203, {}, "anything.example", 200,
                          "host check auto-disabled when an API key is set"))
    env_no_key = {"PUBLIC_URL": f"https://{HOSTNAME}", "PERCHANCE_API_KEY": ""}
    results.append(check(8204, env_no_key, HOSTNAME, 200,
                          "public host allowed while protection is on"))
    results.append(check(8205, env_no_key, "evil.example", 421,
                          "foreign host blocked while protection is on"))
    if all(results):
        print("\nALL HOST HEADER CHECKS PASSED")
        return 0
    print("\nSOME HOST HEADER CHECKS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())

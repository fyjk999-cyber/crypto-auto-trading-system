import os
import sys

REPO = "/Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-local-current"

if os.fork() > 0:
    sys.exit(0)
os.setsid()
if os.fork() > 0:
    sys.exit(0)
with open(REPO + "/.ops/backend_watchdog.log", "ab") as out:
    os.dup2(out.fileno(), 1)
    os.dup2(out.fileno(), 2)
devnull = os.open(os.devnull, os.O_RDONLY)
os.dup2(devnull, 0)
env = dict(os.environ)
env["PATH"] = os.path.expanduser("~/.local/bin") + ":" + env.get("PATH", "")
os.execve("/bin/bash", ["/bin/bash", REPO + "/.ops/backend_watchdog.sh"], env)

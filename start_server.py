import subprocess
import sys
import time

proc = subprocess.Popen(
    [sys.executable, "run.py"],
    stdout=open("server_bg.log", "w"),
    stderr=subprocess.STDOUT,
)
print(f"Started PID: {proc.pid}")

time.sleep(3)

# Verify it's running by checking the log
with open("server_bg.log") as f:
    content = f.read()
    print(content[-300:] if len(content) > 300 else content)
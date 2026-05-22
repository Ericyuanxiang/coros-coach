"""Quick test: start server, init, tools/list."""
import subprocess, json, time

proc = subprocess.Popen(
    ["C:/coros-mcp/coros-mcp-main/.venv/Scripts/python.exe", "server.py"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, cwd="C:/coros-mcp/coros-mcp-main",
)

def send(req):
    line = json.dumps(req)
    print(f">> {line[:120]}...")
    proc.stdin.write(line + "\n")
    proc.stdin.flush()

def recv(timeout=3.0):
    import select
    # On Windows, select on pipes doesn't work. Use a different approach.
    # We'll use a polling approach with readline.
    proc.stdout._reader_buffer = b""  # hack: clear any buffered data
    # Actually just use readline with timeout via threading
    import threading
    result = []
    def reader():
        try:
            line = proc.stdout.readline()
            if line:
                result.append(line.strip())
        except:
            pass
    t = threading.Thread(target=reader)
    t.start()
    t.join(timeout)
    if t.is_alive():
        print("<< (timeout)")
        return None
    if result:
        print(f"<< {result[0][:200]}")
        return result[0]
    return None

# Init
send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}})
time.sleep(2)
response = recv(3)
if response:
    print("Init OK")
else:
    # read stderr
    err = proc.stderr.readline()
    if err:
        print(f"STDERR: {err}")

# Initialized notification (not a request, no response expected)
send({"jsonrpc":"2.0","method":"notifications/initialized","params":{}})
time.sleep(0.5)

# List tools
send({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}})
response = recv(10)

if response:
    data = json.loads(response)
    if "result" in data:
        tools = [t["name"] for t in data["result"].get("tools", [])]
        print(f"Tools: {tools}")
    else:
        print(f"Error: {data}")
else:
    print("No response to tools/list after 10s")
    # Try reading stderr
    import os
    os.set_blocking(proc.stderr.fileno(), False)
    try:
        errors = proc.stderr.read()
        if errors:
            print(f"STDERR after: {errors[:500]}")
    except:
        pass

proc.terminate()

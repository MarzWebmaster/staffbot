with open("/root/staffbot/hermes-gateway/gateway_api.py") as f:
    gw = f.read()

old = 'subprocess.run(["pkill", "-HUP", "-f", "hermes server"], timeout=5)'
new = (
    'import os, signal\n'
    '        for pid in os.listdir("/proc"):\n'
    '            if pid.isdigit():\n'
    '                try:\n'
    '                    with open(f"/proc/{pid}/cmdline") as pf:\n'
    '                        cmdline = pf.read()\n'
    '                    if "hermes" in cmdline and "server" in cmdline:\n'
    '                        os.kill(int(pid), signal.SIGHUP)\n'
    '                        break\n'
    '                except:\n'
    '                    pass'
)

gw = gw.replace(old, new)
with open("/root/staffbot/hermes-gateway/gateway_api.py", "w") as f:
    f.write(gw)
print("OK" if "os.kill" in open("/root/staffbot/hermes-gateway/gateway_api.py").read() else "FAIL")

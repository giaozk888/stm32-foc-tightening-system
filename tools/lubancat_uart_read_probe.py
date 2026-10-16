"""Linux read-only UART evidence probe; no transmit, scanning or reset API."""
import argparse
import fcntl
import json
import os
import select
import stat
import termios
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('device')
parser.add_argument('--seconds', type=int, default=15)
args = parser.parse_args()
if not args.device.startswith('/dev/') or not 1 <= args.seconds <= 60:
    parser.error('explicit /dev device and 1–60 seconds required')
fd = os.open(args.device, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
try:
    if not stat.S_ISCHR(os.fstat(fd).st_mode):
        raise ValueError('not a character device')
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    settings = termios.tcgetattr(fd)
    settings[0] = 0
    settings[1] = 0
    settings[2] = termios.CS8 | termios.CLOCAL | termios.CREAD
    settings[3] = 0
    settings[4] = settings[5] = termios.B115200
    settings[6][termios.VMIN] = settings[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, settings)
    end = time.monotonic() + args.seconds
    count = lines = 0
    while time.monotonic() < end:
        ready, _, _ = select.select([fd], [], [], max(0.0, min(0.2, end - time.monotonic())))
        if ready:
            chunk = os.read(fd, 4096)
            count += len(chunk)
            lines += chunk.count(b'\n')
    print(json.dumps({'device': args.device, 'seconds': args.seconds,
                      'bytes': count, 'newlines': lines, 'transmitted_bytes': 0}))
finally:
    os.close(fd)

"""Inspect staged files for publication mistakes without printing secrets.

Read-only: never accesses serial ports, debuggers or device backups.
Findings require review; secret heuristics may also flag deliberate test data.
"""
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'private-key': re.compile(rb'-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----'),
    'github-token': re.compile(rb'(?:github_pat_[A-Za-z0-9_]{30,}|gh[pousr]_[A-Za-z0-9]{30,})'),
    'cloud-access-key': re.compile(rb'(?:AKIA|ASIA)[A-Z0-9]{16}'),
    'api-secret': re.compile(rb'sk-(?:proj-|ant-)?[A-Za-z0-9_-]{32,}'),
    'credential-url': re.compile(rb'https?://[^\s/"\']+:[^\s/@"\']+@'),
    'secret-literal': re.compile(
        rb'(?i)(?:password|passwd|api[_-]?key|secret[_-]?key|access[_-]?token|wifi[_-]?(?:password|pass|psk))'
        rb'\s*[=:]\s*["\']([^"\'\r\n]{6,})["\']'),
}
BLOCKED = re.compile(r'(?i)(?:^|/)(?:safety_backups|refactor_backups|local_config|tmp|'
    r'node_modules|__pycache__|\.ssh|\.aws)(?:/|$)|'
    r'(?:^|/)(?:build[^/]*|[^/]*_build)/|'
    r'\.(?:bin|elf|hex|exe|pem|key|pfx|p12|sqlite3?|sr|zip|7z)$')


def git(*args):
    return subprocess.run(['git',*args],cwd=ROOT,check=True,capture_output=True).stdout


def audit():
    findings, large = [], []
    count = total = 0
    entries = []
    for entry in git('ls-files','--stage','-z').split(b'\0'):
        if not entry: continue
        info,name = entry.split(b'\t',1)
        mode,oid,stage = info.split()
        path = name.decode('utf-8')
        if mode == b'160000': continue
        entries.append((path, oid))
    if not entries:
        raise RuntimeError('No staged files to inspect; run git add first')
    objects = subprocess.run(
        ['git', 'cat-file', '--batch'], cwd=ROOT, check=True, capture_output=True,
        input=b''.join(oid + b'\n' for _, oid in entries)).stdout
    cursor = 0
    for path, oid in entries:
        header_end = objects.index(b'\n', cursor)
        object_id, kind, size = objects[cursor:header_end].split()
        if object_id != oid or kind != b'blob':
            raise RuntimeError('Unexpected staged object')
        cursor = header_end + 1
        data = objects[cursor:cursor + int(size)]
        cursor += int(size) + 1
        count += 1
        if BLOCKED.search(path): findings.append(dict(path=path,kind='excluded-path'))
        total += len(data)
        if len(data) > 10*1024*1024: large.append(dict(path=path,bytes=len(data)))
        if b'\0' in data: continue
        for kind,pattern in PATTERNS.items():
            for match in pattern.finditer(data):
                findings.append(dict(path=path,line=data.count(b'\n',0,match.start())+1,kind=kind))
    result = dict(files=count,bytes=total,large_files=large,findings=findings)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 1 if findings or large else 0


if __name__ == '__main__':
    sys.exit(audit())

"""Check tracked publishable files for private artifacts and common credential patterns."""
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]
result = subprocess.run(['git', 'ls-files', '-z'], cwd=root, capture_output=True)
if result.returncode != 0:
    raise SystemExit('Initialize and stage the publishable Git repository before running this check.')
files = [root / name for name in result.stdout.decode().split('\0') if name]
problems = []
for path in files:
    relative = path.relative_to(root)
    if path.suffix.lower() in {'.key', '.pem', '.p12', '.pfx', '.db', '.sqlite', '.zip', '.enc', '.xlsx'} or any(p in {'business_files', '.venv', 'certs', 'backups'} for p in relative.parts):
        problems.append(f'{relative}: private or generated artifact')
        continue
    if path.suffix.lower() == '.png' and relative.parts[:3] == ('frontend', 'dist', 'assets'):
        if not path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
            problems.append(f'{relative}: invalid image asset')
        continue
    content = path.read_text(encoding='utf-8')
    for pattern in [r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', r'gh[pousr]_[A-Za-z0-9]{30,}', r'github_pat_[A-Za-z0-9_]{30,}', r'AKIA[A-Z0-9]{16}', r'/Users/[A-Za-z0-9_-]+/']:
        if re.search(pattern, content):
            problems.append(f'{relative}: credential or machine-specific path')
            break
if problems:
    print('\n'.join(problems))
    raise SystemExit(1)
print(f'Public source checks passed for {len(files)} tracked files.')

"""Create local Docker credentials once, without printing secrets."""
import os
from pathlib import Path
import secrets
import sys

def main():
    destination = Path(sys.argv[1] if len(sys.argv) > 1 else '.env.docker')
    values = {name: secrets.token_hex(32) for name in (
        'ENTRY_MYSQL_PASSWORD', 'ENTRY_MYSQL_ROOT_PASSWORD',
        'ENTRY_SECRET_KEY', 'ENTRY_SEED_PASSWORD_ADMIN')}
    content = '# Keep this file private and back it up with the data volumes.\n'
    content += ''.join(f'{key}={value}\n' for key, value in values.items())
    content += 'ENTRY_IMAGE_TAG=v1.0.0\nENTRY_HTTP_PORT=8125\n'
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit('Configuration already exists; preserved without modification.')
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)
    print(f'Created {destination}. Initial admin password is stored in ENTRY_SEED_PASSWORD_ADMIN.')

if __name__ == '__main__':
    main()

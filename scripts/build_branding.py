"""Copy the maintainable brand extension into the served static directory."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
for suffix in ('js', 'css'):
    shutil.copyfile(root / 'frontend' / 'src' / f'branding.{suffix}', root / 'frontend' / 'dist' / 'assets' / f'branding.{suffix}')
print('Brand assets synchronized.')

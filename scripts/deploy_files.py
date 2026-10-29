"""Emit an explicit source allowlist for deployment; never include user data or secrets."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
paths = [root / name for name in (
    'Dockerfile', 'Dockerfile.inference', '.dockerignore', '.gitignore', 'render.yaml', 'package.json',
    'package-lock.json', 'requirements-cloud.txt', 'README.md', 'AGENTS.md', 'PROJECT_STATE.md',
    'scripts/math.cjs', 'scripts/browser-sdk.js', 'scripts/package_plugin.py',
    'deploy/schema.sql', 'deploy/README.md', 'deploy/FRIENDS.md', 'inklab/weights/LICENSE',
) if (root / name).exists()]
paths += sorted((root / 'inklab').glob('*.py'))
paths += [p for p in sorted((root / 'static').iterdir()) if p.is_file() and p.suffix in {'.html', '.css', '.js', '.svg'}]
print(json.dumps([{'path': p.relative_to(root).as_posix(), 'mode': '100644', 'type': 'blob',
                  'content': p.read_text(encoding='utf-8-sig')} for p in paths], ensure_ascii=True))

"""Build a portable plugin package after a public HTTPS deployment exists."""
import argparse
import json
import zipfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def build(public_url, destination):
    url = urlparse(public_url)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
        raise ValueError('Use the deployed HTTPS origin, without credentials or a path.')
    origin = public_url.rstrip('/')
    manifest = {
        '$schema': 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json',
        'name': 'inklab', 'version': '0.2.0',
        'description': 'Private handwriting samples and engineering math PDF annotation.',
        'extensions': {'com.openai': {'interface': {
            'displayName': 'InkLab', 'shortDescription': '내 필기로 공학 수식과 PDF 작성',
            'websiteURL': origin, 'privacyPolicyURL': origin + '/privacy.html',
            'defaultPrompt': ['내 PDF를 열고 필기 프로필로 수식과 설명을 배치해줘.'],
        }}},
    }
    mcp = {
        '$schema': 'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json',
        'mcpServers': {'inklab': {
            'type': 'streamable-http', 'url': origin + '/mcp',
            'extensions': {'com.openai': {'auth': {'type': 'oauth', 'client': {'mode': 'dcr'}}}},
        }},
    }
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, value in [('plugin.json', manifest), ('mcp.json', mcp)]:
            archive.writestr(name, json.dumps(value, ensure_ascii=False, indent=2))
        archive.writestr('README.md', '# InkLab\n\nMCP: ' + origin + '/mcp\n\nEach user signs in to their own workspace. Public directory listing requires separate review.\n')
        friends = ROOT / 'deploy/FRIENDS.md'
        if friends.exists():
            archive.write(friends, 'FRIENDS.md')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('public_url')
    parser.add_argument('--output', default=str(ROOT / 'output/inklab-plugin.zip'))
    args = parser.parse_args()
    print(build(args.public_url, args.output))

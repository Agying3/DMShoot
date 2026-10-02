import os, json, urllib.request

token = os.environ.get('GITHUB_TOKEN')
if not token:
    raise SystemExit('Set GITHUB_TOKEN before running this script.')

def github_tree(path=''):
    import urllib.parse
    encoded = '/'.join(urllib.parse.quote(p, safe='') for p in path.split('/')) if path else ''
    url = f'https://api.github.com/repos/Agying3/DMShoot/contents/{encoded}?ref=main'
    if not encoded:
        url = url.replace('/contents/', '/contents/?ref=main')
    req = urllib.request.Request(url, headers={'Authorization': f'token {token}'})
    resp = urllib.request.urlopen(req)
    items = json.loads(resp.read())
    files = []
    for item in items:
        if item['type'] == 'file':
            files.append(item['path'])
        elif item['type'] == 'dir':
            files.extend(github_tree(item['path']))
    return files

print('Fetching GitHub file list...')
github_files = set(github_tree())
print(f'GitHub: {len(github_files)} files')

share = 'H:/DMShoot-share'
share_files = set()
for root, dirs, files in os.walk(share):
    for f in files:
        rel = os.path.relpath(os.path.join(root, f), share).replace('\\', '/')
        if '.git/' in rel or '__pycache__' in rel:
            continue
        share_files.add(rel)
print(f'Share: {len(share_files)} files')

only_github = github_files - share_files
only_share = share_files - github_files
common = github_files & share_files

print(f'\n=== Only on GitHub ({len(only_github)}) ===')
for f in sorted(only_github):
    print(f'  + {f}')

print(f'\n=== Only in Share ({len(only_share)}) ===')
for f in sorted(only_share):
    print(f'  - {f}')

print(f'\n=== Common: {len(common)} files ===')

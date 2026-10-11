"""Fetch a pinned public tokenizer asset during setup, never at app runtime."""
from pathlib import Path
import hashlib
import json
import urllib.request

ROOT = Path(__file__).resolve().parent
URL = 'https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken'
SHA256 = '223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7'
directory = ROOT / 'tokenizer-cache'
directory.mkdir(exist_ok=True)
path = directory / hashlib.sha1(URL.encode()).hexdigest()
content = path.read_bytes() if path.exists() else urllib.request.urlopen(URL, timeout=40).read()
assert hashlib.sha256(content).hexdigest() == SHA256, 'Public tokenizer hash mismatch'
path.write_bytes(content)
(ROOT.parent / 'evidence').mkdir(exist_ok=True)
(ROOT.parent / 'evidence' / 'cmdbox-tokenizer-asset.json').write_text(json.dumps(
    dict(url=URL,sha256=SHA256,bytes=len(content),purpose='Offline LiteLLM import only; no inference'),
    indent=2) + '\n',encoding='utf8')
print('Pinned public tokenizer ready for offline import.')

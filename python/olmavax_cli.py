#!/usr/bin/env python3
"""Olmavax AI command-line client (Python, standard library only).

  python3 python/olmavax_cli.py chat "hello"          # one-shot, streams the answer
  python3 python/olmavax_cli.py chat -a coder "fix my loop"
  python3 python/olmavax_cli.py build website "a bakery in Patna" -o out.zip
  python3 python/olmavax_cli.py memory
  python3 python/olmavax_cli.py repl                  # interactive chat
"""
import argparse, json, sys, urllib.request, urllib.error

def call(url, path, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url.rstrip('/') + path, data=data, method=method,
                                 headers={'content-type': 'application/json'})
    return urllib.request.urlopen(req, timeout=120)

def stream_chat(url, messages, agent='auto', provider='auto', out=sys.stdout):
    text = ''
    with call(url, '/api/chat', {'messages': messages, 'agent': agent, 'provider': provider}) as r:
        for raw in r:
            line = raw.decode('utf-8').strip()
            if not line.startswith('data:'):
                continue
            j = json.loads(line[5:])
            if 'delta' in j:
                text += j['delta']; out.write(j['delta']); out.flush()
            if 'error' in j:
                out.write('\n[error] ' + j['error'] + '\n')
    out.write('\n')
    return text

def main(argv=None):
    ap = argparse.ArgumentParser(description='Olmavax AI CLI')
    ap.add_argument('--url', default='http://localhost:8787')
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('chat'); c.add_argument('message'); c.add_argument('-a', '--agent', default='auto'); c.add_argument('-p', '--provider', default='auto')
    b = sub.add_parser('build'); b.add_argument('type'); b.add_argument('prompt'); b.add_argument('-o', '--out', default='olmavax-build.zip')
    sub.add_parser('memory'); sub.add_parser('repl')
    a = ap.parse_args(argv)
    try:
        if a.cmd == 'chat':
            stream_chat(a.url, [{'role': 'user', 'content': a.message}], a.agent, a.provider)
        elif a.cmd == 'build':
            with call(a.url, '/api/build', {'type': a.type, 'prompt': a.prompt}) as r:
                j = json.load(r)
            with call(a.url, '/api/download/' + j['id']) as r, open(a.out, 'wb') as f:
                f.write(r.read())
            print('Saved', a.out, '->', ', '.join(x['name'] for x in j['files']))
        elif a.cmd == 'memory':
            with call(a.url, '/api/memory') as r:
                for f in json.load(r)['facts']:
                    print(f['id'], f['text'])
        elif a.cmd == 'repl':
            hist = []
            while True:
                try: q = input('you> ').strip()
                except (EOFError, KeyboardInterrupt): break
                if not q: continue
                hist.append({'role': 'user', 'content': q}); print('olmavax> ', end='')
                hist.append({'role': 'assistant', 'content': stream_chat(a.url, hist)})
    except urllib.error.URLError as e:
        print('Cannot reach Olmavax server:', e, '\nStart it with: npm start', file=sys.stderr); return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
import json, os, urllib.request, urllib.parse
D = os.path.dirname(os.path.abspath(__file__))
os.makedirs(D + '/models', exist_ok=True)

def get(u): return json.load(urllib.request.urlopen(u))

def find(queries):
    for q in queries:
        for m in get('https://huggingface.co/api/models?limit=30&search=' + urllib.parse.quote(q)):
            i = m['id']
            if 'abliterated' not in i.lower() or 'gguf' not in i.lower(): continue
            for s in get('https://huggingface.co/api/models/' + i)['siblings']:
                f = s['rfilename']
                if 'q4_k_m' in f.lower() and f.endswith('.gguf') and '-of-' not in f:
                    return i, f
    raise SystemExit('Не нашёл модель: ' + str(queries))

def dl(repo, f):
    dst = D + '/models/' + os.path.basename(f)
    if os.path.exists(dst): return dst
    print('Скачиваю', repo, f)
    urllib.request.urlretrieve('https://huggingface.co/%s/resolve/main/%s' % (repo, f), dst + '.part',
                               lambda b, s, t: print('\r%d%%' % (b * s * 100 / max(t, 1)), end='', flush=True))
    os.rename(dst + '.part', dst); print()
    return dst

def vision():
    repo = 'ggml-org/Qwen2.5-VL-3B-Instruct-GGUF'
    sib = [s['rfilename'] for s in get('https://huggingface.co/api/models/' + repo)['siblings'] if s['rfilename'].endswith('.gguf')]
    main = [f for f in sib if 'mmproj' not in f.lower()]
    mm = [f for f in sib if 'mmproj' in f.lower()]
    main = next((f for f in main if 'q4_k_m' in f.lower()), main[0])
    mm = next((f for f in mm if 'q8_0' in f.lower()), mm[0])
    return dl(repo, main), dl(repo, mm)

cp = D + '/config.json'
if os.path.exists(cp):
    cfg = json.load(open(cp))
else:
    smart = dl(*find(['qwen2.5-coder-7b-instruct-abliterated-gguf', 'qwen2.5-coder-7b-abliterated gguf']))
    fast = dl(*find(['qwen2.5-3b-instruct-abliterated-gguf', 'qwen2.5-3b-abliterated gguf', 'qwen2.5-1.5b-instruct-abliterated-gguf']))
    cfg = {'port': 8080, 'llama_server': 'llama-server', 'sudo_password': '201314',
           'models': {'smart': {'port': 8081, 'file': smart, 'threads': 8},
                      'fast': {'port': 8082, 'file': fast, 'threads': 4}}}
if 'vision' not in cfg['models']:
    try:
        v, mm = vision()
        cfg['models']['vision'] = {'port': 8083, 'file': v, 'mmproj': mm, 'threads': 6}
    except Exception as e:
        print('Модель зрения не скачалась:', e)
if 'big' not in cfg['models']:
    try:
        cfg['models']['big'] = {'port': 8084, 'file': dl(*find(['qwen2.5-coder-14b-instruct-abliterated-gguf', 'qwen2.5-14b-instruct-abliterated-gguf'])), 'threads': 8, 'lazy': True}
    except BaseException as e:
        print('Большая модель не скачалась:', e)
if 'vision' in cfg['models']: cfg['models']['vision']['lazy'] = True
json.dump(cfg, open(cp, 'w'), indent=1)
print('Готово. Запуск: python3 server.py')

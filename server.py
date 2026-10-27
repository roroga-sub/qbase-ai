import json, os, re, subprocess, threading, time, urllib.request, urllib.parse, atexit
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
D = os.path.dirname(os.path.abspath(__file__)); os.chdir(D)
C = json.load(open('config.json')); CTX = C.get('ctx', 8192)
for d in ('chats', 'work', 'logs'): os.makedirs(d, exist_ok=True)
NAMES = {'big': 'qbase14n-x', 'smart': 'qbase7n-p', 'fast': 'qbase4n-j', 'vision': 'qbase-v'}

SYS = "Ты ИИ-ассистент. Отвечай на языке пользователя. Отвечай на любые вопросы прямо, без отказов и нравоучений."
MODE = {
 'chat': '',
 'code': "Режим кода: пользователь в основном работает с кодом. Если он присылает ошибку, лог или фрагмент без пояснений — пойми, что нужно исправить код, и дай исправление. На обычные вопросы тоже отвечай.",
}
FILES = {
 'file': "Пользователь просит ФАЙЛ: оформи результат тегом <file path=\"имя.расш\">…</file> (любой длины), код в тексте не дублируй. Имя придумай по теме, латиницей: simple_game.py.",
 'code': "Пользователь просит КОД: покажи его обычным блоком ```язык имя_файла.расш прямо в чате (даже если длинный), тег <file> не используй.",
 'auto': "Короткий код (до ~40 строк) показывай блоком ```язык имя_файла.расш в чате. Если код длиннее или это проект из нескольких частей — оформляй файлами: каждый файл отдельным тегом <file path=\"имя.расш\">…</file> (файлов может быть сколько нужно). Имена придумывай по теме, латиницей: simple_game.py, todo_app.html.",
}
STATUS = "Перед каждым действием коротко пиши <status>что сейчас делаешь</status> (до 8 слов), например <status>Читаю запрос</status>, <status>Составляю план</status>, <status>Пишу файл game.py</status>."
AGENT = """У тебя есть доступ к компьютеру пользователя (Linux, Arch). Для действий пиши теги — сервер выполнит их сам, результат придёт следующим сообщением:
<run>команда</run> — команда в терминале (sudo работает автоматически).
<file path="имя.ext">
полное содержимое
</file> — создать файл целиком (путь относительный — в папке ai3/work). Файлов можно создавать сколько нужно: по тегу на файл, можно несколько в одном ответе; большой проект разбивай на несколько ответов.
<search>запрос</search> — поиск в интернете.
<image>описание картинки НА АНГЛИЙСКОМ</image> — сгенерировать картинку (1-3 минуты).
Пример:
<file path="hello.py">
print('hi')
</file>
<run>python3 hello.py</run>
После тегов остановись и жди результат. Файлы пиши полностью, без «...» и без markdown-обёртки внутри тега. Для задач из нескольких шагов сначала напиши «ПЛАН:» и 3-6 пунктов. Когда всё готово — коротко напиши итог без тегов."""
CHECK = "После создания программы проверь её: запусти (долгие и графические программы — через `timeout 10 ...`), посмотри результат и исправь ошибки, только потом пиши итог."
THINK = [
 "Отвечай сразу и коротко. Не пиши размышления, ничего не перепроверяй и не проверяй на компьютере.",
 "Сначала напиши короткие размышления в теге <think>…</think> (2-5 строк: что именно просит пользователь, что нужно сделать), затем сам ответ.",
 "Сначала подробно подумай в теге <think>…</think>: пойми, что имел в виду пользователь, продумай план и возможные ошибки; затем ответ. Перепроверь каждую функцию.",
]
ACT = re.compile(r'<file path="([^"]+)">\n?(.*?)(?:</file>|$)|<run>(.*?)(?:</run>|$)|<search>(.*?)(?:</search>|$)|<image>(.*?)(?:</image>|$)', re.S)

def unfence(c): return re.sub(r'^\s*```[\w+#-]*\n(.*?)\n?```\s*$', r'\1', c, flags=re.S)
def nothink(t):
    t = re.sub(r'<status>.*?(</status>|$)', '', t, flags=re.S)
    return re.sub(r'^\s*<think>.*?(</think>|$)', '', t, count=1, flags=re.S)
def kind_of(t): return 'file' if t[0] else 'search' if t[3].strip() else 'image' if t[4].strip() else 'run'
def intent(ms):
    u = [m for m in ms if m['role'] == 'user' and not m.get('hidden')]
    t = re.sub(r'\n*\[Файл.*', '', u[-1].get('content', '') if u else '', flags=re.S)[:400].lower()
    return 'file' if re.search(r'файл|file', t) else 'code' if re.search(r'(^|[^а-яёa-z])(код|code)', t) else 'auto'

def sysmsg(mode, think, custom='', mem='', agent=False, it='auto'):
    th = int(think)
    t = [SYS, MODE.get(mode, ''), THINK[th], FILES[it]]
    if th >= 1 or agent: t.append(STATUS)
    if agent:
        t.append(AGENT)
        if th >= 1: t.append(CHECK)
    if custom: t.append('Инструкции пользователя: ' + custom[:1000])
    if mem: t.append('Журнал прошлых запросов пользователя (твоя память). Если он просит переделать или вспомнить, что делали, опирайся на него; код прошлой работы читай из файлов в ai3/work.\n' + mem)
    return {'role': 'system', 'content': ' '.join(t)}

# ---------- модели (big и vision стартуют лениво, при первом запросе) ----------
PR = {}
def start(k):
    m = C['models'][k]
    cmd = [C['llama_server'], '-m', m['file'], '--port', str(m['port']), '-c', str(CTX), '-t', str(m['threads']), '-ngl', str(m.get('ngl', 0))]
    if m.get('mmproj'): cmd += ['--mmproj', m['mmproj']]
    lf = open('logs/%s.log' % k, 'w'); PR[k] = subprocess.Popen(cmd, stdout=lf, stderr=lf)
def down(k): return k not in PR or PR[k].poll() is not None
def ensure(k):
    if down(k): start(k)
    u = 'http://127.0.0.1:%d/health' % C['models'][k]['port']
    for _ in range(300):
        try:
            if urllib.request.urlopen(u, timeout=2).status == 200: return
        except Exception: pass
        if PR[k].poll() is not None: raise RuntimeError('модель %s не запустилась (см. logs/%s.log)' % (k, k))
        time.sleep(2)
    raise RuntimeError('модель %s слишком долго грузится' % k)

def llama(model, msgs, stream, temp=0.7, mx=2048):
    ensure(model)
    b = json.dumps({'messages': msgs, 'stream': stream, 'temperature': temp, 'max_tokens': mx}).encode()
    u = 'http://127.0.0.1:%d/v1/chat/completions' % C['models'][model]['port']
    return urllib.request.urlopen(urllib.request.Request(u, b, {'Content-Type': 'application/json'}), timeout=1800)

def fit(ms, budget):
    out, n = [], 0
    for m in reversed(ms):
        n += len(m['content'])
        if n > budget and out: break
        out.append(m)
    out.reverse()
    while len(out) > 1 and out[0]['role'] != 'user': out.pop(0)
    return out

def vmsg(m):
    return {'role': m['role'], 'content': [{'type': 'text', 'text': m['content'] or 'Опиши изображение.'}] +
            [{'type': 'image_url', 'image_url': {'url': u}} for u in m['images']]}

def prep(b):
    mem = memtail() if b.get('mem', True) else ''
    mx = int(b.get('max', 2048)); it = intent(b['messages'])
    sm = sysmsg(b.get('mode', 'chat'), b.get('think', 1), b.get('custom', ''), mem, b.get('agent'), it)
    ms = [m for m in b['messages'] if m.get('content') or m.get('images')]
    vi = [i for i, m in enumerate(ms) if m.get('images')]
    model, nov = b['model'], False
    vis = bool(vi) and vi[-1] >= len(ms) - 6
    if vis:
        if 'vision' in C['models']: model = 'vision'
        else: vis, nov = False, True
    cl = [dict({'role': m['role'], 'content': m.get('content', '')}, **({'images': m['images']} if vis and i == vi[-1] else {})) for i, m in enumerate(ms)]
    fitted = fit(cl, max(2000, int((CTX - mx) * 2.2) - len(sm['content']) - (1500 if vis else 0)))
    out = [sm] + [vmsg(m) if m.get('images') else {'role': m['role'], 'content': m['content']} for m in fitted]
    return model, out, {'mem': len(mem), 'msgs': len(fitted), 'cut': len(cl) - len(fitted), 'model': NAMES.get(model, model), 'novision': nov, 'intent': it}, mx

# ---------- инструменты ----------
def run(cmd):
    sudo = 'sudo' in cmd
    if sudo: cmd = re.sub(r'\bsudo\b', 'sudo -S -p ""', cmd)
    try:
        p = subprocess.run(cmd, shell=True, cwd='work', input=(C['sudo_password'] + '\n') if sudo else '',
                           capture_output=True, text=True, timeout=300)
        return p.returncode, (p.stdout + p.stderr)[-4000:] or '(нет вывода)'
    except Exception as e:
        return -1, str(e)

def wfile(p, c):
    p = os.path.expanduser(p); p = p if os.path.isabs(p) else os.path.join('work', p)
    try:
        os.makedirs(os.path.dirname(p) or '.', exist_ok=True)
        open(p, 'w').write(unfence(c)); return 'записан: ' + os.path.abspath(p)
    except Exception as e:
        return 'ошибка: %s' % e

def search(q):
    try:
        req = urllib.request.Request('https://html.duckduckgo.com/html/', ('q=' + urllib.parse.quote(q)).encode(), {'User-Agent': 'Mozilla/5.0'})
        h = urllib.request.urlopen(req, timeout=20).read().decode('utf-8', 'ignore')
        cl = lambda s: re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s)).strip()
        it = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>', h, re.S)[:5]
        return '\n'.join('%d. %s — %s (%s)' % (i + 1, cl(t), cl(sn), urllib.parse.unquote(u.split('uddg=')[-1].split('&')[0])) for i, (u, t, sn) in enumerate(it)) or '(ничего не найдено)'
    except Exception as e:
        return 'ошибка поиска: %s' % e

def genimg(prompt):
    sd, mdl = C.get('sd_bin'), C.get('sd_model')
    if not sd or not mdl or not os.path.exists(mdl): return 'err', 'Генерация картинок не установлена: запусти bash setup_image.sh'
    os.makedirs('work/images', exist_ok=True); n = 'img_%d.png' % time.time(); out = 'work/images/' + n
    try:
        p = subprocess.run([sd, '-m', mdl, '-p', prompt[:400], '--cfg-scale', '1.0', '--steps', '4', '--sampling-method', 'euler',
                            '-H', '512', '-W', '512', '-t', str(C.get('sd_threads', 8)), '-o', out], capture_output=True, text=True, timeout=1500)
        return ('ok', '/img/' + n) if os.path.exists(out) else ('err', (p.stderr or p.stdout)[-500:])
    except Exception as e:
        return 'err', str(e)

def act(kind, fp, fc, cmd, q, im):
    t = time.time()
    if kind == 'file':
        out = wfile(fp, fc); st = 'err' if out.startswith('ошибка') else 'ok'; line = 'Файл %s: %s' % (fp, out)
    elif kind == 'search':
        out = search(q.strip()); st = 'err' if out.startswith('ошибка') else 'ok'; line = 'Результаты поиска «%s»:\n%s' % (q.strip(), out)
    elif kind == 'image':
        st, out = genimg(im.strip()); line = ('Изображение создано: ' + out) if st == 'ok' else 'Не удалось создать изображение: ' + out
    else:
        c = unfence(cmd).strip(); code, out = run(c); st = 'ok' if code == 0 else 'err'; line = '$ %s\n(код %s)\n%s' % (c, code, out)
    return {'st': st, 'out': out, 'dur': round(time.time() - t, 1), 'line': line}

# ---------- память ----------
def memadd(line):
    with open('memory.md', 'a') as f: f.write(line + '\n')
    if os.path.getsize('memory.md') > 24000:
        t = open('memory.md').read()[-16000:]; i = t.find('\n- [')
        open('memory.md', 'w').write(t[i + 1:] if i >= 0 else t)

def memtail(n=2500):
    try: t = open('memory.md').read()[-n:]
    except OSError: return ''
    i = t.find('\n- ['); return t[i + 1:] if i >= 0 and len(t) >= n else t

def memlog(b, reply):
    if not b.get('mem', True) or not reply.strip(): return
    last = (b.get('messages') or [{}])[-1]
    nm = {'file': 'файл ', 'search': 'поиск ', 'image': 'картинка '}
    ac = '; '.join((nm[k] + (t[0] or t[3] or t[4]).strip()[:50]) if k != 'run' else 'cmd: ' + t[2].strip().split('\n')[0][:60] for t in ACT.findall(nothink(reply)) for k in [kind_of(t)])
    r = re.sub(r'\s+', ' ', ACT.sub('', nothink(reply))).strip()[:250]
    if last.get('hidden'): memadd('  шаг: ' + (ac or r))
    else: memadd('- [%s] Запрос: %s\n  Ответ: %s%s' % (time.strftime('%d.%m %H:%M'), re.sub(r'\s+', ' ', last.get('content', ''))[:200], r, ('\n  Действия: ' + ac) if ac else ''))

def put(cid, obj):
    obj['t'] = time.time(); p = 'chats/%s.json' % cid
    json.dump(obj, open(p + '.tmp', 'w')); os.replace(p + '.tmp', p)

# ---------- AFK: задача выполняется на сервере, браузер можно закрыть ----------
J = {'running': False, 'stop': False, 'cid': '', 'seen': True}
def evt(m, t): m['ev'].append([round(time.time() - m['t0'] / 1000, 1), t])
def fin(m): m.update(run=False, hold=False, dur=round(time.time() - m['t0'] / 1000, 1), phase=''); evt(m, 'Готово за %.1fс' % m['dur'])

def gen(model, msgs, b, mx, m, save):
    r = llama(model, msgs, True, float(b.get('temp', 0.7)), mx); last = 0; first = True
    try:
        for l in r:
            if J['stop']: break
            if not l.startswith(b'data: {'): continue
            try: j = json.loads(l[6:])
            except Exception: continue
            d = ((j.get('choices') or [{}])[0].get('delta') or {}).get('content') or ''
            if d:
                if first: first = False; evt(m, 'Первый токен')
                m['content'] += d
                ss = re.findall(r'<status>(.*?)</status>', m['content'], re.S)
                for x in ss[m['sn']:]: evt(m, '→ ' + x.strip()); m['last'] = x.strip()
                m['sn'] = len(ss)
                th = bool(re.match(r'\s*<think>', re.sub(r'<status>.*?(</status>|$)', '', m['content'], flags=re.S))) and '</think>' not in m['content']
                m['phase'] = ('Размышляет' if th else (m.get('last') or 'Пишет ответ')) + ' · %d симв.' % len(m['content'])
            t = j.get('timings')
            if t and t.get('predicted_per_second'): evt(m, 'Скорость: %.1f ток/с, токенов: %s' % (t['predicted_per_second'], t.get('predicted_n')))
            if time.time() - last > 1.2: save(); last = time.time()
    finally:
        r.close()

def job(b):
    chat = b['chat']; cid = chat['id'] = re.sub(r'\W', '', chat['id'])
    chat['running'] = True; J.update(running=True, stop=False, cid=cid, seen=False)
    save = lambda: put(cid, chat)
    try:
        for _ in range(25):
            model, msgs, info, mx = prep(dict(b, messages=chat['msgs'], agent=True))
            m = {'role': 'assistant', 'content': '', 't0': int(time.time() * 1000), 'run': True, 'hold': True, 'sn': 0, 'intent': info['intent'],
                 'phase': 'Читает контекст', 'ev': [], 'acts': []}
            chat['msgs'].append(m)
            evt(m, 'AFK: запрос → %s (сообщений %d, память %d симв.)' % (info['model'], info['msgs'], info['mem'])); save()
            gen(model, msgs, b, mx, m, save)
            if J['stop']: m['content'] += '\n\n⏹ остановлено'
            acts = ACT.findall(nothink(m['content']))
            if J['stop'] or not acts: fin(m); break
            m['acts'] = [{'st': 'wait'} for _ in acts]; m['hold'] = False; res = []
            for i, t in enumerate(acts):
                if J['stop']: break
                k = kind_of(t); a = m['acts'][i]; a['st'] = 'run'
                lab = (t[0] if k == 'file' else t[3] if k == 'search' else t[4] if k == 'image' else unfence(t[2])).strip()[:60]
                m['phase'] = {'file': 'Пишет файл', 'run': 'Выполняет', 'search': 'Ищет в интернете', 'image': 'Рисует картинку'}[k] + ': ' + lab; evt(m, m['phase']); save()
                r = act(k, t[0], t[1], t[2], t[3], t[4])
                a.update(st=r['st'], out=r['out'], dur=r['dur']); res.append(r['line'])
                evt(m, ('Готово: ' if r['st'] == 'ok' else 'Ошибка: ') + lab[:40] + ' → ' + re.sub(r'\s+', ' ', r['out'])[:80]); m['phase'] = 'Смотрит результат'; save()
            fin(m)
            if J['stop']: break
            chat['msgs'].append({'role': 'user', 'content': 'Результат:\n' + '\n'.join(res), 'hidden': 1}); save()
    except Exception as e:
        chat['msgs'].append({'role': 'assistant', 'content': '[Ошибка AFK: %s]' % e})
    chat['running'] = False; J['running'] = False; save()
    if b.get('mem', True):
        u = [m for m in chat['msgs'] if m['role'] == 'user' and not m.get('hidden')]
        a = [m for m in chat['msgs'] if m['role'] == 'assistant']
        if u and a: memadd('- [%s] AFK-запрос: %s\n  Итог: %s' % (time.strftime('%d.%m %H:%M'), re.sub(r'\s+', ' ', u[-1]['content'])[:200], re.sub(r'\s+', ' ', nothink(a[-1]['content']))[:250]))

class H(BaseHTTPRequestHandler):
    def log_message(s, *a): pass
    def local(s):
        ip = s.client_address[0]
        return ip in ('127.0.0.1', '::1') or ip == s.connection.getsockname()[0]
    def reply(s, code, body, ct='application/json'):
        if not isinstance(body, bytes): body = json.dumps(body).encode()
        s.send_response(code); s.send_header('Content-Type', ct)
        s.send_header('Content-Length', str(len(body))); s.end_headers(); s.wfile.write(body)
    def jb(s): return json.loads(s.rfile.read(int(s.headers.get('Content-Length', 0))) or b'{}')

    def do_GET(s):
        p = s.path
        if p == '/': return s.reply(200, open('index.html', 'rb').read(), 'text/html; charset=utf-8')
        if p.startswith('/img/'):
            f = 'work/images/' + re.sub(r'[^\w.\-]', '', p[5:])
            return s.reply(200, open(f, 'rb').read(), 'image/png') if os.path.exists(f) else s.reply(404, {})
        if p == '/api/chats':
            L = [json.load(open('chats/' + f)) for f in os.listdir('chats') if f.endswith('.json')]
            return s.reply(200, sorted([{'id': c['id'], 'title': c['title'], 't': c.get('t', 0)} for c in L], key=lambda x: -x['t']))
        if p.startswith('/api/chat/'): return s.reply(200, open('chats/%s.json' % re.sub(r'\W', '', p[10:]), 'rb').read())
        if p == '/api/mem': return s.reply(200, open('memory.md', 'rb').read() if os.path.exists('memory.md') else b'', 'text/plain; charset=utf-8')
        if p == '/api/job': return s.reply(200, J)
        if p == '/api/info': return s.reply(200, {'local': s.local()})
        s.reply(404, {})

    def do_POST(s):
        b, p = s.jb(), s.path
        if p == '/api/chat':
            s.send_response(200); s.send_header('Content-Type', 'text/event-stream'); s.end_headers()
            r, reply = None, ''
            try:
                model, msgs, info, mx = prep(b)
                s.wfile.write(('data: ' + json.dumps({'ev': info}) + '\n\n').encode()); s.wfile.flush()
                if down(model): s.wfile.write(('data: ' + json.dumps({'loading': NAMES[model]}) + '\n\n').encode()); s.wfile.flush()
                r = llama(model, msgs, True, float(b.get('temp', 0.7)), mx)
                for l in r:
                    s.wfile.write(l); s.wfile.flush()
                    if l.startswith(b'data: {'):
                        try: reply += ((json.loads(l[6:]).get('choices') or [{}])[0].get('delta') or {}).get('content') or ''
                        except Exception: pass
            except (BrokenPipeError, ConnectionResetError): pass
            except Exception as e:
                try: s.wfile.write(('data: ' + json.dumps({'choices': [{'delta': {'content': '\n[Ошибка модели: %s]' % e}}]}) + '\n\n').encode())
                except Exception: pass
            finally:
                if r: r.close()
            memlog(b, reply); return
        if p == '/api/save':
            cid = re.sub(r'\W', '', b['id']); b['id'] = cid
            if J['running'] and J['cid'] == cid: return s.reply(200, {'skip': 1})
            put(cid, b); return s.reply(200, {})
        if p == '/api/del':
            try: os.remove('chats/%s.json' % re.sub(r'\W', '', b['id']))
            except OSError: pass
            return s.reply(200, {})
        if p == '/api/memclear': open('memory.md', 'w').close(); return s.reply(200, {})
        if p == '/api/jobseen': J['seen'] = True; return s.reply(200, {})
        if p == '/api/jobstop': J['stop'] = True; return s.reply(200, {})
        if p in ('/api/act', '/api/job', '/api/upload') and not s.local(): return s.reply(403, {'error': 'только с этого компьютера'})
        if p == '/api/act': return s.reply(200, act(b['kind'], b.get('path', ''), b.get('content', ''), b.get('cmd', ''), b.get('q', ''), b.get('img', '')))
        if p == '/api/upload':
            n = re.sub(r'[^\w.\-]', '_', b['name']); os.makedirs('work/uploads', exist_ok=True)
            import base64; open('work/uploads/' + n, 'wb').write(base64.b64decode(b['data'])); return s.reply(200, {'path': 'work/uploads/' + n})
        if p == '/api/job':
            if J['running']: return s.reply(200, {'error': 'AFK-задача уже выполняется'})
            threading.Thread(target=job, args=(b,), daemon=True).start(); return s.reply(200, {})
        s.reply(404, {})

for k, m in C['models'].items():
    if not m.get('lazy'): start(k)
atexit.register(lambda: [p.terminate() for p in PR.values()])
print('Открой http://localhost:%d' % C['port'])
ThreadingHTTPServer(('0.0.0.0', C['port']), H).serve_forever()

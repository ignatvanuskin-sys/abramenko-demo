import urllib.request, json, uuid, time
base = 'https://abramenko-demo-production.up.railway.app'
sid = 'audit3-' + uuid.uuid4().hex[:6]

def post(m):
    d = json.dumps({'session_id': sid, 'message': m}, ensure_ascii=False).encode()
    r = urllib.request.Request(base + '/api/chat', data=d, headers={'Content-Type': 'application/json'})
    t0 = time.monotonic()
    resp = json.loads(urllib.request.urlopen(r, timeout=15).read().decode())
    return resp, (time.monotonic() - t0) * 1000

seq = [
    ('хочу балаяж', 'clarify_hair'),
    ('окрашены', 'branch'),
    ('Жамбыла', 'await_date'),
    ('завтра', 'await_slot'),
    ('1', 'await_name'),
    ('Айгерим', 'await_phone'),
    ('+7 707 123 45 67', 'done'),
]
ok = True
for m, exp in seq:
    r, dt = post(m)
    step = r.get('step')
    if step != exp:
        ok = False
        print('FAIL', m, '->', step, '|', r.get('message', '')[:60])
    print(f"{m!r} -> {dt:.0f}ms step={step} | {r.get('message', '')[:70]}")
print('final done:', r.get('done'))
print('TZ:', [seg for seg in r.get('message', '').split() if ':' in seg][:1])
print('E2E PROD (slots+DB):', 'PASS' if ok and r.get('done') else 'FAIL')

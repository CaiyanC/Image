import json, urllib.request
base='http://127.0.0.1:5275/api'
q1='\u98ce\u66b4\u7089pro-\u6c7d\u7089\u7248\u7684\u4e3b\u8981\u5356\u70b9\u662f\u4ec0\u4e48'
q2='\u4ed6\u8be5\u5982\u4f55\u6e05\u6d17\u4fdd\u517b'

def post_json(url, payload, headers=None, timeout=180):
    data=json.dumps(payload, ensure_ascii=True).encode('ascii')
    req=urllib.request.Request(url, data=data, headers={**(headers or {}), 'Content-Type':'application/json'}, method='POST')
    return urllib.request.urlopen(req, timeout=timeout)
with post_json(base+'/auth/login', {'username':'admin','password':'admin123'}, timeout=20) as r:
    token=json.loads(r.read().decode('utf-8'))['access_token']
headers={'Authorization':f'Bearer {token}'}

def loads_maybe(x):
    if isinstance(x, str):
        try: return loads_maybe(json.loads(x))
        except Exception: return x
    return x

def ask(q, cid=None):
    payload={'question':q}
    if cid: payload['conversation_id']=cid
    events=[]; event=None; data=[]
    def flush():
        nonlocal event, data
        if event or data:
            text='\n'.join(data)
            events.append({'event':event or 'message','data':loads_maybe(text) if text else None})
        event=None; data=[]
    with post_json(base+'/customer-service/ask-stream', payload, headers=headers, timeout=180) as resp:
        for bline in resp:
            line=bline.decode('utf-8', errors='replace').rstrip('\r\n')
            if line=='': flush(); continue
            if line.startswith('event:'): event=line[6:].strip()
            elif line.startswith('data:'): data.append(line[5:].strip())
    flush(); return events

def answer_text(events):
    out=[]
    for e in events:
        d=e['data']
        if e['event']=='content' and isinstance(d,dict): out.append(str(d.get('content') or ''))
        if e['event']=='answer_delta' and isinstance(d,dict): out.append(str(d.get('text') or ''))
    return ''.join(out)

def summarize(label, ev):
    meta=next((e['data'] for e in ev if e['event']=='meta'),{})
    trace=next((e['data'] for e in ev if e['event']=='trace'),{})
    print(label+'_EVENTS', [e['event'] for e in ev])
    print(label+'_CONVERSATION', meta.get('conversation_id') if isinstance(meta,dict) else None)
    print(label+'_ANSWER', answer_text(ev))
    print(label+'_META', json.dumps(meta, ensure_ascii=False, default=str))
    print(label+'_TRACE', json.dumps(trace, ensure_ascii=False, default=str))
    return meta, trace

ev1=ask(q1)
meta1, trace1=summarize('ROUND1', ev1)
cid=meta1.get('conversation_id') if isinstance(meta1,dict) else None
ev2=ask(q2, cid)
meta2, trace2=summarize('ROUND2', ev2)

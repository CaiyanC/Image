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

def get_event(events, name):
    return next((e['data'] for e in events if e['event']==name), {})

ev1=ask(q1)
meta1=get_event(ev1,'meta'); trace1=get_event(ev1,'trace')
cid=meta1.get('conversation_id') if isinstance(meta1,dict) else None
ev2=ask(q2,cid)
meta2=get_event(ev2,'meta'); trace2=get_event(ev2,'trace')
summary={
 'round1': {
   'conversation_id': cid,
   'answer': answer_text(ev1),
   'trace': trace1,
   'evidence': meta1.get('evidence') if isinstance(meta1,dict) else None,
   'result_skus': trace1.get('result_skus') if isinstance(trace1,dict) else None,
 },
 'round2': {
   'conversation_id': meta2.get('conversation_id') if isinstance(meta2,dict) else None,
   'answer': answer_text(ev2),
   'trace': trace2,
   'evidence': meta2.get('evidence') if isinstance(meta2,dict) else None,
   'results_summary': [
     {
       'sku': r.get('sku'),
       'product_name_cn': r.get('product_name_cn'),
       'field_values': r.get('field_values'),
       'knowledge_matches': [
         {'sku': k.get('sku'), 'content': k.get('content'), 'score': k.get('score')}
         for k in (r.get('knowledge_matches') or [])[:3]
       ]
     }
     for r in (meta2.get('results') or [])
     if isinstance(r, dict)
   ] if isinstance(meta2,dict) else None,
   'semantic_tool_results': [
     {
       'tool': t.get('tool'), 'query': t.get('query'), 'sku': t.get('sku'), 'count': t.get('count'),
       'results': [{'sku': x.get('sku'), 'content': x.get('content'), 'score': x.get('score')} for x in (t.get('results') or [])]
     }
     for t in (((meta2.get('debug') or {}).get('tool_results') or []) if isinstance(meta2,dict) else [])
     if isinstance(t, dict) and t.get('tool') == 'semantic_search_knowledge'
   ]
 }
}
print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))

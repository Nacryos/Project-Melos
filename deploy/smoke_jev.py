"""Opt-in live Jev check: at most two requests, the second must use the cache."""
import argparse
import http.cookiejar
import json
from urllib.request import build_opener, HTTPCookieProcessor, Request

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--allow-paid',action='store_true',required=True)
parser.add_argument('--origin',default='https://greeklyric.com')
args=parser.parse_args()
opener=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
body=json.dumps({'form':'πέμπην','passage_id':'dcc-sappho:brothers-poem'},ensure_ascii=False).encode()
for number in range(2):
    request=Request(args.origin.rstrip('/')+'/api/classify-context',data=body,
                    headers={'Content-Type':'application/json'})
    with opener.open(request,timeout=90) as response:
        result=json.load(response)
    print(json.dumps({k:result.get(k) for k in ('status','model','candidate_id','cache_hit','reason','usage')},ensure_ascii=False),flush=True)
    assert result.get('model','').startswith('jev-'), 'No verified Jev response'
    assert isinstance(result.get('cache_hit'),bool)
    assert result['status'] in ('proposed','abstained')
    if number:
        assert result['cache_hit'] is True, 'Repeated comparison was not cached'
print('Live Jev response and repeat cache hit verified; source evidence unchanged.')

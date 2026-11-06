"""Source-derived parity with Flutter@ce66ae7 mock_auth_test.dart.

This does not claim a Dart runtime run. Fixed vectors below are independent
hashlib/HMAC calculations; cases mirror Dart's response bodies and challenges.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import web_ui as ui

NOW = 1789387200


def digest(nc='00000001', cnonce='demo-cnonce', uri='/auth/digest', **changes):
    params = dict(username='demo', realm='mock', nonce='demo-digest-nonce', uri=uri,
                  qop='auth', nc=nc, cnonce=cnonce,
                  response=ui.auth_digest_response(method='GET', uri=uri, nc=nc, cnonce=cnonce), opaque='demo-digest-opaque')
    params.update(changes)
    return {'Authorization': 'Digest ' + ', '.join(f'{k}="{v}"' for k, v in params.items() if v is not None)}


def signed(nonce='n1', timestamp=str(NOW), path='/auth/hmac', method='GET', pairs=(), body=''):
    return {'method': method, 'path': path, 'query_pairs': list(pairs), 'body': body,
            'headers': {'X-Key-Id': 'demo-key', 'X-Timestamp': timestamp, 'X-Nonce': nonce,
                        'X-Signature': ui.auth_hmac_signature(method=method, path=path, timestamp=timestamp, nonce=nonce,
                                                             query_string=ui.auth_query_pairs(pairs), body=body)}}


class AuthContractTests(unittest.TestCase):
    def setUp(self):
        self.auth = ui.MockAuthHandler(clock=lambda: NOW)

    def ask(self, path, headers=None, **extra):
        return self.auth.handle({'path': '/auth/' + path, 'headers': headers or {}, **extra})

    def expect(self, result, status, reason=None, **body):
        self.assertEqual(result['status'], status)
        if reason:
            self.assertEqual(result['body'], {'ok': False, 'error': 'forbidden' if status == 403 else 'unauthorized', 'reason': reason, **body})
        else:
            self.assertEqual(result['body'], {'ok': True, **body})

    def test_bearer_source_cases_and_headers(self):
        for value, status, reason in [('',401,'missing_authorization'),('Token nope',401,'malformed_authorization'),
                                     ('Bearer demo-expired-token',401,'expired'),('Bearer nope',401,'invalid_token')]:
            with self.subTest(value=value):
                result=self.ask('bearer', {'Authorization':value});self.expect(result,status,reason)
                self.assertIn('Bearer realm="mock"', result['headers']['www-authenticate'])
        self.expect(self.ask('bearer', {'AUTHORIZATION':'bEaReR demo-bearer-token'}),200,scheme='bearer',audience=ui.AUTH_AUDIENCE)
        self.expect(self.ask('bearer', {'authorization':'Bearer demo-wrong-aud-token'}),403,'wrong_audience',expectedAudience=ui.AUTH_AUDIENCE)
        for raw in (' Bearer demo-bearer-token','Bearer demo-bearer-token ', 'Bearer'):
            self.expect(self.ask('bearer', {'authorization':raw}),401,'malformed_authorization')

    def test_api_key_header_precedence_and_empty_fallback(self):
        self.expect(self.ask('api-key'),401,'missing_api_key')
        self.expect(self.ask('api-key',{'x-api-key':'wrong'},query={'api_key':'demo-api-key'}),403,'invalid_api_key')
        self.expect(self.ask('api-key',{'X-Api-Key':'demo-api-key'}),200,scheme='api_key',via='header')
        self.expect(self.ask('api-key',{'x-api-key':''},query={'api_key':'demo-api-key'}),200,scheme='api_key',via='query')

    def test_basic_challenge_credentials_utf8_and_base64(self):
        r=self.ask('basic');self.expect(r,401,'missing_authorization')
        self.assertEqual(r['headers'], {'www-authenticate':'Basic realm="mock", charset="UTF-8"'})
        for raw in ('ZGVtbzpzM2NyZXQ=', 'ZGVtbzpzM2NyZXQ%3D'):
            self.expect(self.ask('basic', {'authorization':'Basic '+raw}),200,scheme='basic',user='demo')
        for value, reason in [('demo:wrong','invalid_credentials'), ('demo:s3cret:extra','invalid_credentials'),
                              (':password','malformed_authorization'),('demo','malformed_authorization')]:
            raw=base64.b64encode(value.encode()).decode()
            self.expect(self.ask('basic',{'authorization':'Basic '+raw}),401,reason)
        for raw in ('%%%','a','!!!!','/w==','ZGVtbzpzM2NyZXQ===','ZGVtbzpzM2NyZXQ'):
            self.expect(self.ask('basic',{'authorization':'Basic '+raw}),401,'malformed_authorization')

    def test_fixed_signature_vectors(self):
        self.assertEqual(ui.auth_digest_response(method='GET',uri='/auth/digest',nc='00000001',cnonce='demo-cnonce'),
                         'cfdbbedfad6274737a7a33b04745d965')
        self.assertEqual(ui.auth_hmac_signature(method='GET',path='/auth/hmac',timestamp=str(NOW),nonce='n3'),
                         '9b517acf13ca5e844461f5d877c0a6753e8f0adf1803f21ab0b80300f7368efe')

    def test_inventory_keeps_archive_blockers_and_source_hashes(self):
        import hashlib
        data=json.loads((Path(__file__).resolve().parents[1]/'docs/flutter-migration-inventory.json').read_text())
        rows={r['path']:r for r in data['non_catalogue_files']}
        self.assertFalse(data['archive_ready'])
        self.assertEqual(rows['lib/shared/http/mock_auth.dart']['status'],'successor')
        self.assertEqual(rows['lib/shared/http/digest_nc.dart']['status'],'successor')
        self.assertEqual(rows['lib/shared/http/auth_matrix.dart']['status'],'partial')
        self.assertGreater(data['status_counts_outside_catalogues']['unreviewed'],0)
        self.assertEqual(data['source_commit'],'ce66ae7198dbe74ed62f70180fbff260e4acd14d')

    def test_digest_nc_source_vectors_and_boundaries(self):
        for value, expected in [('00000000',0),('00000001',1),('0000000a',10),('0000000A',10),('ffffffff',0xffffffff)]:
            self.assertEqual(ui.digest_nc_parse(value),expected)
            if expected:self.assertEqual(ui.digest_nc_format(expected),value.lower())
        for value in ('10','0000000g','000000001','00000001\n','０００００００１','-0000001',' 0000001'):
            self.assertIsNone(ui.digest_nc_parse(value))
        for value in (0,-1,0x100000000,True,1.0):
            with self.assertRaises(ValueError):ui.digest_nc_format(value)

    def test_digest_all_rejection_paths(self):
        r=self.ask('digest');self.expect(r,401,'missing_authorization')
        self.assertEqual(r['headers'],{'www-authenticate':ui.AUTH_DIGEST_CHALLENGE})
        self.expect(self.ask('digest',{'authorization':'Basic xx'}),401,'malformed_authorization')
        cases=[({'username':None},'malformed_authorization'),({'qop':None},'missing_qop_params'),
               ({'nc':None},'missing_qop_params'),({'cnonce':''},'missing_qop_params'),
               ({'uri':'/other'},'uri_mismatch'),({'algorithm':'SHA-256'},'unsupported_algorithm'),
               ({'opaque':None},'invalid_opaque'),({'nonce':'wrong'},'invalid_credentials'),
               ({'response':'deadbeef'},'invalid_credentials')]
        for params, reason in cases:
            with self.subTest(params=params):self.expect(self.ask('digest',digest(**params)),401,reason)
        for nc in ('00000000','10','0000000g','000000001','00000001\n'):
            self.expect(self.ask('digest',digest(nc=nc)),401,'invalid_nc')

    def test_digest_replay_monotonic_counts_and_invalid_does_not_consume(self):
        for nc in ('00000001','0000000a','0000000B','ffffffff'):
            self.expect(self.ask('digest',digest(nc=nc)),200,scheme='digest',user='demo')
            self.expect(self.ask('digest',digest(nc=nc)),401,'digest_replay')
        self.expect(self.ask('digest',digest(nc='00000009')),401,'digest_replay')
        self.expect(self.ask('digest',digest(cnonce='fresh',response='bad')),401,'invalid_credentials')
        self.expect(self.ask('digest',digest(cnonce='fresh')),200,scheme='digest',user='demo')
        self.expect(self.ask('digest',digest(cnonce='another')),200,scheme='digest',user='demo')

    def test_digest_query_binding_order_duplicates_and_raw_target(self):
        pairs=[['x','a b'],['x','日本語'],['punct',"!~*'()"]]
        query="x=a+b&x=%E6%97%A5%E6%9C%AC%E8%AA%9E&punct=%21~%2A%27%28%29"
        self.assertEqual(ui.auth_query_pairs(pairs),query)
        target='/auth/digest?'+query
        self.expect(self.ask('digest',digest(uri=target),query_pairs=pairs),200,scheme='digest',user='demo')
        self.expect(self.ask('digest',digest(uri=target),query_pairs=pairs[::-1]),401,'uri_mismatch')
        raw='/auth/digest?x=a%20b'
        self.expect(self.ask('digest',digest(uri=raw,cnonce='raw'),request_target=raw),200,scheme='digest',user='demo')
        self.expect(self.ask('digest',digest(),query={'x':'1'}),401,'uri_mismatch')
        self.expect(self.ask('digest/',digest(uri='/auth/digest/',cnonce='slash')),200,scheme='digest',user='demo')

    def test_hmac_required_unknown_timestamp_skew_and_replay(self):
        self.expect(self.ask('hmac'),401,'missing_hmac_headers',required=['X-Key-Id','X-Timestamp','X-Nonce','X-Signature'])
        for header,value,status,reason in [('X-Key-Id','unknown',403,'unknown_key_id'),('X-Timestamp','oops',401,'malformed_timestamp'),('X-Timestamp','9'*5000,401,'malformed_timestamp'),
                                           ('X-Timestamp','1',401,'timestamp_skew'),('X-Signature','bad',401,'invalid_signature'),
                                           ('X-Signature','日本語',401,'invalid_signature')]:
            req=signed();req['headers'][header]=value
            self.expect(self.auth.handle(req),status,reason)
        req=signed();self.expect(self.auth.handle(req),200,scheme='hmac',keyId='demo-key')
        self.expect(self.auth.handle(req),401,'replay')
        req['headers']['X-Signature']='bad'
        self.expect(self.auth.handle(req),401,'replay') # Dart checks replay before signature.
        for offset in (-301,-300,300,301):
            req=signed(nonce=str(offset),timestamp=str(NOW+offset))
            if abs(offset)>300:self.expect(self.auth.handle(req),401,'timestamp_skew')
            else:self.expect(self.auth.handle(req),200,scheme='hmac',keyId='demo-key')

    def test_hmac_binds_method_path_ordered_query_body_and_preserves_failed_nonce(self):
        req=signed(method='post',path='/auth/hmac/',pairs=[['x','1'],['x','2']],body='日本語\nbody')
        for change in ({'path':'/auth/hmac'},{'method':'PUT'},{'query_pairs':[['x','2'],['x','1']]},{'body':'changed'}):
            self.expect(self.auth.handle({**req,**change}),401,'invalid_signature')
        self.expect(self.auth.handle(req),200,scheme='hmac',keyId='demo-key')
        self.expect(self.auth.handle(req),401,'replay')

    def test_concurrent_replays_only_one_success(self):
        for request in (signed(),{'path':'/auth/digest','headers':digest()}):
            with ThreadPoolExecutor(max_workers=8) as pool:
                statuses=list(pool.map(lambda _:self.auth.handle(request)['status'],range(16)))
            self.assertEqual(statuses.count(200),1)
            self.assertEqual(statuses.count(401),15)

    def test_rate_limit_unknown_and_matrix(self):
        result=self.ask('rate-limited')
        self.assertEqual(result,{'status':429,'headers':{'retry-after':'1'},'body':{'ok':False,'error':'rate_limited','reason':'too_many_requests'}})
        self.assertIsNone(self.ask('other'));self.assertIsNone(self.auth.handle(ui.auth_matrix('none')))
        expected=[None,200,401,403,200,200,200,401,401,401,429]
        for scenario,status in zip(ui.AUTH_SCENARIOS,expected):
            request=ui.auth_matrix(scenario);result=self.auth.handle(request)
            self.assertEqual(result['status'] if result else None,status,scenario)
        for scenario in ('digest','hmac'):
            result=ui.MockAuthHandler().handle(ui.auth_prepare(scenario))
            self.assertEqual(result['status'],200)
        for invalid in (None,{}, {'path':'http://example.com'}, {'path':'/auth/hmac','headers':[]}, {'path':'/auth/hmac','query_pairs':['bad']}, {'path':'/auth/hmac','url':'https://example.com'}):
            with self.assertRaises(ValueError):self.auth.handle(invalid)


class AuthBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ui.pattern_bridge(0)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.port=cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(5)

    def post(self,request,path='/mock-auth',headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
        data=json.dumps(request).encode()
        conn.request('POST',path,data,{'Content-Type':'application/json',**(headers or {})})
        r=conn.getresponse();result=r.status,dict((k.lower(),v) for k,v in r.getheaders()),json.loads(r.read());conn.close();return result

    def test_demo_page_and_security_headers(self):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
        conn.request('GET','/auth.html')
        response=conn.getresponse();page=response.read().decode();conn.close()
        self.assertEqual(response.status,200)
        self.assertEqual(response.getheader('X-Frame-Options'),'DENY')
        self.assertIn('id="auth-request"',page)
        self.assertIn('credentials:"omit"',page)

    def test_auth_navigation_is_only_on_the_live_bridge(self):
        for page in (ui.patterns_html(), ui.patterns_document(),
                     ui.example_pages()['examples/patterns.html']):
            self.assertNotIn('href="/auth.html"',page)
            self.assertIn('python3 web_ui.py --pattern-serve',page)
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
        conn.request('GET','/')
        response=conn.getresponse();page=response.read().decode();conn.close()
        self.assertEqual(response.status,200)
        self.assertIn('href="/auth.html"',page)

    def test_real_status_challenges_retry_and_replay(self):
        status,headers,body=self.post(ui.auth_matrix('digestChallengeOnly'))
        self.assertEqual(status,401);self.assertEqual(headers['www-authenticate'],ui.AUTH_DIGEST_CHALLENGE)
        self.assertEqual(headers['cache-control'],'no-store')
        status,headers,body=self.post(ui.auth_matrix('rateLimited'))
        self.assertEqual(status,429);self.assertEqual(headers['retry-after'],'1')
        for scenario in ('digest','hmac'):
            status,headers,request=self.post({'scenario':scenario},'/mock-auth/prepare');self.assertEqual(status,200)
            self.assertEqual(self.post(request)[0],200)
            self.assertEqual(self.post(request)[0],401)
        self.assertEqual(self.post(ui.auth_matrix('bearer'))[0],200)
        self.assertEqual(self.post({'path':'/auth/other'})[0],404)

    def test_existing_bridge_guards_and_payload_validation(self):
        req=ui.auth_matrix('bearer')
        for headers,status in [({'Origin':'https://foreign.test'},403),({'Host':'evil.test'},403),
                               ({'Content-Type':'text/plain'},415),({'Transfer-Encoding':'chunked'},411)]:
            self.assertEqual(self.post(req,headers=headers)[0],status)
        self.assertEqual(self.post({'path':'/auth/hmac','body':'x'*65536})[0],413)
        self.assertEqual(self.post({'url':'https://example.com'})[0],400)
        status,headers,_=self.post(req,headers={'Origin':f'http://127.0.0.1:{self.port}'})
        self.assertEqual(status,200);self.assertEqual(headers['access-control-allow-origin'],f'http://127.0.0.1:{self.port}')
        for invalid in ({'scenario':'bad'},{'scenario':[]},{'scenario':'digest','extra':1}):
            self.assertEqual(self.post(invalid,'/mock-auth/prepare')[0],400)


if __name__=='__main__':unittest.main()

"""Isolated OAuth/MCP contract fixture. It never touches the user's Dreams account."""
import base64
import copy
import hashlib
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit


def map_fixture():
    return {'revision': 10, 'nodes': [
        {'id': 'atlas', 'kind': 'project', 'name': 'Atlas Studio', 'fields': {'links': 'https://www.figma.com/design/atlasFile/Brand'}, 'measurements': []},
        {'id': 'birch', 'kind': 'service', 'name': 'Birch Client', 'fields': {}, 'measurements': []}
    ], 'edges': []}


class Provider:
    def __init__(self):
        self.map = map_fixture()
        self.registrations = {}
        self.codes = {}
        self.tokens = set()
        self.refreshes = set()
        self.requests = {}
        self.writes = []
        self.fail_after_write = False
        self.force_conflict = False
        self.refresh_count = 0
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.handler())
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def handler(self):
        provider = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, status, data):
                raw = json.dumps(data).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == '/.well-known/oauth-authorization-server':
                    return self.send(200, {'issuer': provider.origin, 'authorization_endpoint': provider.origin + '/oauth/authorize', 'token_endpoint': provider.origin + '/oauth/token', 'registration_endpoint': provider.origin + '/oauth/register'})
                if path == '/oauth/authorize':
                    query = {k:v[0] for k,v in parse_qs(urlsplit(self.path).query).items()}
                    registration = provider.registrations.get(query['client_id'])
                    assert registration and query['redirect_uri'] in registration['redirect_uris']
                    assert query['code_challenge_method'] == 'S256'
                    assert query['resource'] == provider.origin + '/mcp'
                    code = secrets.token_hex(12)
                    provider.codes[code] = query
                    self.send_response(303)
                    self.send_header('Location', query['redirect_uri'] + '?' + urlencode({'code': code, 'state': query['state'], 'iss': provider.origin}))
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                return self.send(404, {})

            def do_POST(self):
                path = urlsplit(self.path).path
                raw = self.rfile.read(int(self.headers['Content-Length']))
                data = {k:v[0] for k,v in parse_qs(raw.decode()).items()} if path == '/oauth/token' else json.loads(raw)
                if path == '/oauth/register':
                    assert data['token_endpoint_auth_method'] == 'none'
                    ident = secrets.token_hex(12)
                    provider.registrations[ident] = data
                    return self.send(201, {'client_id': ident})
                if path == '/oauth/token':
                    if data['grant_type'] == 'authorization_code':
                        query = provider.codes.pop(data['code'])
                        challenge = base64.urlsafe_b64encode(hashlib.sha256(data['code_verifier'].encode()).digest()).decode().rstrip('=')
                        assert challenge == query['code_challenge']
                        assert data['redirect_uri'] == query['redirect_uri'] and data['client_id'] == query['client_id']
                    else:
                        assert data['refresh_token'] in provider.refreshes
                        provider.refreshes.remove(data['refresh_token'])
                        provider.refresh_count += 1
                    assert data['resource'] == provider.origin + '/mcp'
                    token, refresh = secrets.token_hex(16), secrets.token_hex(16)
                    provider.tokens.add(token)
                    provider.refreshes.add(refresh)
                    return self.send(200, {'access_token': token, 'refresh_token': refresh, 'token_type': 'Bearer', 'expires_in': 3600})
                if path != '/mcp' or self.headers.get('Authorization', '').removeprefix('Bearer ') not in provider.tokens:
                    return self.send(401, {})
                if data['method'] == 'initialize':
                    result = {'protocolVersion': '2025-03-26', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'Isolated Dreams', 'version': '1'}}
                elif data['method'] == 'notifications/initialized':
                    self.send_response(202)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                else:
                    assert data['method'] == 'tools/call'
                    name, args = data['params']['name'], data['params']['arguments']
                    if name == 'get_map':
                        output = copy.deepcopy(provider.map)
                    else:
                        assert name == 'apply_changes'
                        if args['requestId'] in provider.requests:
                            output = provider.requests[args['requestId']]
                        elif provider.force_conflict or args['baseRevision'] != provider.map['revision']:
                            provider.force_conflict = False
                            result = {'isError': True, 'content': [{'type': 'text', 'text': 'The map changed elsewhere. Your draft is kept; review it and save again.'}]}
                            return self.send(200, {'jsonrpc': '2.0', 'id': data['id'], 'result': result})
                        else:
                            for command in args['commands']:
                                assert command['type'] == 'record_measurement'
                                node = next(n for n in provider.map['nodes'] if n['id'] == command['id'])
                                measurement = command['measurement']
                                assert measurement['basis'] == 'Worked' and measurement['metric'] == 'workedHours'
                                node['measurements'] = [m for m in node['measurements'] if m['id'] != measurement['id']] + [copy.deepcopy(measurement)]
                            provider.map['revision'] += 1
                            output = {'revision': provider.map['revision'], 'requestId': args['requestId']}
                            provider.requests[args['requestId']] = output
                            provider.writes.append(copy.deepcopy(args))
                            if provider.fail_after_write:
                                provider.fail_after_write = False
                                return self.send(503, {})
                    result = {'content': [{'type': 'text', 'text': json.dumps(output)}]}
                # Exercise SSE, the transport used by streamable MCP servers.
                body = ('event: message\ndata: ' + json.dumps({'jsonrpc': '2.0', 'id': data['id'], 'result': result}) + '\n\n').encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        return Handler

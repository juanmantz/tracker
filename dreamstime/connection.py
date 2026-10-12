"""Native OAuth/PKCE client for the existing Dreams MCP service.

Credentials never enter the dashboard or an exported diagnostic report.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

ORIGIN = 'https://dreams.checklists.workers.dev'


class ConnectionError(ValueError):
    pass


class Conflict(ConnectionError):
    pass


class Rejected(ConnectionError):
    pass


class DreamsConnection:
    def __init__(self, directory, port, origin=ORIGIN):
        self.origin = origin.rstrip('/')
        self.resource = self.origin + '/mcp'
        self.redirect = f'http://127.0.0.1:{port}/oauth/callback'
        self.path = Path(directory) / 'dreams-credentials.json'
        self.lock = threading.RLock()
        self.pending = None
        self.session = None
        self.protocol = '2025-03-26'
        self.counter = 0
        self.credentials = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.error = None

    def status(self):
        return {'connected': bool(self.credentials.get('access_token')), 'connecting': bool(self.pending), 'error': self.error}

    def save(self):
        temp = self.path.with_suffix('.tmp')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(self.credentials, handle)
        os.chmod(temp, 0o600)
        os.replace(temp, self.path)

    def request(self, url, data=None, *, form=False, headers=None):
        body = None if data is None else (urlencode(data).encode() if form else json.dumps(data).encode())
        request = Request(url, data=body, headers={**({'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json'} if body is not None else {}), **(headers or {})})
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read(16 * 1024 * 1024).decode()
                return raw, response.headers
        except HTTPError as exc:
            # Do not echo remote bodies: they can contain codes or tokens.
            if exc.code == 401:
                raise ConnectionError('Dreams sign-in expired. Connect Dreams again.') from None
            raise ConnectionError(f'Dreams returned HTTP {exc.code}. Try again.') from None
        except (URLError, TimeoutError, OSError):
            raise ConnectionError('Could not reach Dreams. Your hours remain saved; retry when online.') from None

    def begin(self):
        with self.lock:
            metadata = json.loads(self.request(self.origin + '/.well-known/oauth-authorization-server')[0])
            # Discovery cannot redirect tokens to a different host.
            for name in ('authorization_endpoint', 'token_endpoint', 'registration_endpoint'):
                if not metadata.get(name, '').startswith(self.origin + '/'):
                    raise ConnectionError('Dreams returned an unexpected sign-in endpoint.')
            registration = json.loads(self.request(metadata['registration_endpoint'], {
                'client_name': 'Dreams Time', 'redirect_uris': [self.redirect],
                'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code'],
                'token_endpoint_auth_method': 'none'
            })[0])
            verifier = secrets.token_urlsafe(48)
            state = secrets.token_urlsafe(32)
            self.pending = {'state': state, 'verifier': verifier, 'created': time.time(),
                            'client_id': registration['client_id'], 'token_endpoint': metadata['token_endpoint'],
                            'issuer': metadata.get('issuer', self.origin)}
            self.error = None
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            return metadata['authorization_endpoint'] + '?' + urlencode({
                'client_id': registration['client_id'], 'redirect_uri': self.redirect,
                'response_type': 'code', 'scope': 'mcp:read mcp:write offline_access',
                'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256', 'resource': self.resource
            })

    def finish(self, query):
        with self.lock:
            pending = self.pending
            state = query.get('state', [''])[0]
            if not pending or time.time() - pending['created'] > 600 or not hmac.compare_digest(state, pending['state']):
                raise ConnectionError('This sign-in link expired or is invalid. Connect Dreams again.')
            self.pending = None  # consume once, including denied authorizations
            if query.get('error'):
                raise ConnectionError('Dreams connection was cancelled. You can connect again anytime.')
            if query.get('iss', [''])[0] != pending['issuer'] or not query.get('code', [''])[0]:
                raise ConnectionError('Dreams returned an invalid authorization response.')
            tokens = json.loads(self.request(pending['token_endpoint'], {
                'grant_type': 'authorization_code', 'code': query['code'][0],
                'redirect_uri': self.redirect, 'client_id': pending['client_id'],
                'code_verifier': pending['verifier'], 'resource': self.resource
            }, form=True)[0])
            self.credentials = {'client_id': pending['client_id'], 'token_endpoint': pending['token_endpoint']}
            self.accept_tokens(tokens)
            self.session = None
            self.error = None

    def accept_tokens(self, tokens):
        if not tokens.get('access_token') or tokens.get('token_type', 'Bearer').lower() != 'bearer':
            raise ConnectionError('Dreams did not return a usable sign-in token.')
        self.credentials.update(access_token=tokens['access_token'], expires_at=time.time() + float(tokens.get('expires_in', 3600)))
        if tokens.get('refresh_token'):
            self.credentials['refresh_token'] = tokens['refresh_token']
        self.save()

    def access_token(self):
        if not self.credentials.get('access_token'):
            raise ConnectionError('Connect Dreams first.')
        if time.time() >= self.credentials.get('expires_at', 0) - 60:
            if not self.credentials.get('refresh_token'):
                raise ConnectionError('Dreams sign-in expired. Connect Dreams again.')
            tokens = json.loads(self.request(self.credentials['token_endpoint'], {
                'grant_type': 'refresh_token', 'refresh_token': self.credentials['refresh_token'],
                'client_id': self.credentials['client_id'], 'resource': self.resource
            }, form=True)[0])
            self.accept_tokens(tokens)
        return self.credentials['access_token']

    def rpc(self, method, params, notification=False):
        self.counter += 1
        payload = {'jsonrpc': '2.0', 'method': method, 'params': params}
        if not notification:
            payload['id'] = self.counter
        headers = {'Authorization': 'Bearer ' + self.access_token(), 'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': self.protocol}
        if self.session:
            headers['Mcp-Session-Id'] = self.session
        raw, response_headers = self.request(self.resource, payload, headers=headers)
        if response_headers.get('Mcp-Session-Id'):
            self.session = response_headers['Mcp-Session-Id']
        if notification:
            return None
        if response_headers.get('Content-Type', '').startswith('text/event-stream'):
            replies = [json.loads(line[5:].strip()) for line in raw.splitlines() if line.startswith('data:') and line[5:].strip()]
            result = next((r for r in replies if r.get('id') == payload['id']), None)
        else:
            result = json.loads(raw)
        if not isinstance(result, dict) or result.get('id') != payload['id'] or result.get('error'):
            raise ConnectionError('Dreams could not complete the request. Retry from the tracker.')
        return result.get('result', {})

    def call(self, name, arguments=None):
        with self.lock:
            if not self.session:
                initialized = self.rpc('initialize', {'protocolVersion': self.protocol, 'capabilities': {}, 'clientInfo': {'name': 'Dreams Time', 'version': '0.5.0'}})
                self.protocol = initialized.get('protocolVersion', self.protocol)
                self.rpc('notifications/initialized', {}, notification=True)
                # Stateless servers return no session ID; still initialized for this call.
            result = self.rpc('tools/call', {'name': name, 'arguments': arguments or {}})
            content = '\n'.join(c['text'] for c in result.get('content', []) if c.get('type') == 'text')
            if result.get('isError'):
                if 'map changed' in content.lower() or ('revision' in content.lower() and any(word in content.lower() for word in ('conflict', 'stale', 'mismatch'))):
                    raise Conflict('Dreams changed since the last read.')
                raise Rejected('Dreams rejected the update. Refresh projects and check assignments before retrying.')
            try:
                return json.loads(content) if content else result.get('structuredContent', {})
            except (json.JSONDecodeError, TypeError):
                raise ConnectionError('Dreams returned an unreadable result.') from None

    def disconnect(self):
        with self.lock:
            self.credentials = {}
            self.pending = self.session = None
            self.error = None
            self.path.unlink(missing_ok=True)

#!/usr/bin/env python3
"""Read-only check of the public sign-in discovery endpoint from macOS.

Never signs in, registers a client, reads account data, or writes measurements.
Only reports status and allowlisted response characteristics, not remote bodies.
"""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

URL = 'https://dreams.checklists.workers.dev/.well-known/oauth-authorization-server'


def check(name, headers):
    request = Request(URL, headers=headers)
    try:
        response = urlopen(request, timeout=20)
    except HTTPError as error:
        response = error
    except (URLError, TimeoutError, OSError) as error:
        return {'profile': name, 'reachable': False, 'error_type': type(error).__name__}
    with response:
        body = response.read(64 * 1024)
        result = {'profile': name, 'status': response.code,
                  'content_type': response.headers.get('Content-Type', ''),
                  'challenge': response.headers.get('cf-mitigated') == 'challenge',
                  'cloudflare_response': bool(response.headers.get('cf-ray'))}
        if response.code == 200:
            try:
                metadata = json.loads(body)
                origin = 'https://dreams.checklists.workers.dev/'
                result['valid_discovery'] = all(
                    isinstance(metadata.get(key), str) and metadata[key].startswith(origin)
                    for key in ('authorization_endpoint', 'token_endpoint', 'registration_endpoint'))
            except (ValueError, TypeError, AttributeError):
                result['valid_discovery'] = False
        elif response.code == 403:
            result['cloudflare_block_page'] = any(marker in body.lower() for marker in
                                                 (b'cloudflare', b'error code: 1010', b'just a moment'))
        return result


if __name__ == '__main__':
    print(json.dumps({'checks': [
        check('installed urllib defaults', {}),
        check('identified native app', {'User-Agent': 'DreamsTime/0.6.1 (macOS)',
                                        'Accept': 'application/json'}),
    ]}, indent=2))

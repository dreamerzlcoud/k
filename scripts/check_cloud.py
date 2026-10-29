"""Read-only live smoke checks. Does not create accounts or send credentials."""
import json
import httpx

ORIGIN = 'https://inklab-shared.onrender.com'
ISSUER = 'https://zpjqncxfqomousknkssq.supabase.co'
with httpx.Client(timeout=60) as client:
    for path, expected in [('/healthz',200),('/auth/config',200),('/login',200),('/mcp',401),('/api/documents',401),('/.well-known/oauth-protected-resource/mcp',200)]:
        response=client.get(ORIGIN+path)
        assert response.status_code==expected,(path,response.status_code,response.text[:250])
        print(path,response.status_code)
        if path=='/auth/config':
            config=response.json()
            assert config['cloud'] and config['mcp_url']==ORIGIN+'/mcp'
        if path.endswith('oauth-protected-resource/mcp'):
            print(json.dumps(response.json()))
    response=client.get(ISSUER+'/.well-known/oauth-authorization-server/auth/v1')
    response.raise_for_status()
    discovery=response.json()
    assert discovery['issuer']==ISSUER+'/auth/v1'
    assert discovery.get('registration_endpoint')
    print('OAuth discovery and dynamic registration advertised')
    response=client.get(ISSUER+'/auth/v1/.well-known/jwks.json')
    response.raise_for_status()
    algorithms=[key.get('alg') for key in response.json()['keys']]
    assert any(alg in ('ES256','RS256') for alg in algorithms),algorithms
    print('Public signing key algorithms:',algorithms)
    response=client.get(ISSUER+'/auth/v1/settings',headers={'apikey':config['publishable_key']})
    response.raise_for_status()
    print('GitHub provider enabled:',response.json().get('external',{}).get('github',False))
    print('GitHub login button enabled:',config.get('github_login',False))

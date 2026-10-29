# Deployment status — 2026-10-28

- Web: https://inklab-shared.onrender.com
- MCP: https://inklab-shared.onrender.com/mcp
- Private source: https://github.com/dreamerzlcoud/inklab
- Render service: `srv-dbgv5hlg1s2s73ccdg5g`, Free, Singapore; first deployment succeeded.
- Supabase: `zpjqncxfqomousknkssq`, Free, Seoul. Private bucket and ownership policies applied. Security advisors returned no warnings.
- Supabase OAuth server and dynamic client registration enabled with user's approval. Site URL and four redirect patterns point only to the InkLab host. Public JWKS serves ES256.
- GitHub login OAuth app: https://github.com/settings/applications/3971834 . App created by user. User is completing client-secret generation and Supabase provider setup; do not retrieve or commit the secret.
- Render `INKLAB_GITHUB_LOGIN=1` saved and deployment triggered.
- Live unauthenticated checks passed: health, config, login, 401 for private API/MCP, protected-resource metadata and authorization-server discovery.
- Local tests: 24 passed. Plugin archive generated at `output/inklab-plugin.zip` with actual HTTPS endpoint.
- Remaining: verify GitHub provider login, authenticated PDF generation/storage persistence, and complete ChatGPT custom MCP connection. Public plugin directory submission is separate and has not been done.

No personal assignment files, handwriting samples, private keys, or tokens are in the source repository.

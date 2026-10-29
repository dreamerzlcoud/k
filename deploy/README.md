# InkLab shared deployment

This directory deploys an authenticated remote MCP and browser editor. Local mode remains available. Cloud implementation is tested locally; a live deployment and ChatGPT OAuth round trip must be verified before inviting friends.

## Free deployment

1. Create a dedicated Supabase Free project. Keep the Data API enabled, disable automatic table exposure, and enable automatic RLS. Run `schema.sql` once in its SQL editor.
2. Enable Supabase Auth OAuth Server and Dynamic Client Registration. Set authorization path to `/oauth/consent`. Use asymmetric JWT signing (ES256 or RS256).
3. Deploy this repository as a Render Docker Web Service, Free plan, Singapore, health check `/healthz`. `render.yaml` contains the same settings. Use a single worker.
4. Set `INKLAB_PUBLIC_URL` to the service's HTTPS origin, `SUPABASE_URL` to the project URL, and `SUPABASE_PUBLISHABLE_KEY` to its publishable key. Never use a service-role/secret key. No OpenAI API key is needed in cloud mode.
5. In Supabase Auth URL Configuration, set Site URL to the service origin and allow `/login`, `/login?**`, `/oauth/consent?**`, `/download/**` on that exact origin. Configure a production email provider for verification emails or enable GitHub sign-in and set `INKLAB_GITHUB_LOGIN=1` on Render. Supabase's default mail delivery is limited; verify a friend's email can actually register before sharing.
6. Verify two independent users cannot read one another's documents. Restart the service and verify files persist. Check `/healthz`, unauthorized `/mcp` returns 401 with resource metadata, then complete OAuth in ChatGPT and render/download a PDF.
7. Run `python scripts/package_plugin.py https://YOUR-DEPLOYED-HOST` to generate the portable plugin ZIP. The URL must be the actual deployment. In ChatGPT add the HTTPS `/mcp` endpoint with OAuth. Public plugin directory publication is a separate review process.

## Limits and operations

- Render Free sleeps after inactivity; opening the editor first can wake it before MCP connects. Free tiers have usage limits and are not an uptime guarantee.
- Each user has a 45 MB workspace limit. Snapshots are stored in a private Supabase bucket under an owner-only RLS policy. All requests use that user's JWT; the server has no administrative storage key.
- Each request currently loads a complete workspace snapshot, and changed workspaces create a new snapshot with a compare-and-swap database update. This is intended for a small friend beta; large PDFs and frequent previews consume Supabase egress quickly. Monitor quota and stop new uploads before the free limit is exhausted. No automatic paid upgrade is configured.
- Old snapshots are removed after a successful commit. Failed cleanup may leave an orphan; periodically compare bucket objects with `inklab_workspaces.archive_path`, retaining referenced objects. Deletion requests require deleting that user's storage objects and workspace row, not only their Auth user.
- Complete `static/privacy.html` with the operator's contact and retention policy before public directory submission. Dependency license obligations, including PyMuPDF AGPL/commercial licensing, also apply to deployment.
- Real handwriting learning, automatic character segmentation, and LMS submission are not implemented. Registered character crops replace glyphs while MathJax preserves mathematical layout. Missing glyphs use a fallback and are reported.

References: [OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins), [ChatGPT connection](https://developers.openai.com/plugins/deploy/connect-chatgpt), [Supabase MCP OAuth](https://supabase.com/docs/guides/auth/oauth-server/mcp-authentication), [Render Free](https://render.com/docs/free).

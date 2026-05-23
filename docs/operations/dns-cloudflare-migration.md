# DNS migration to Cloudflare

**Goal:** Move all four versawiki domains from Namecheap's nameservers to Cloudflare so we get free SSL, fast DNS, DDoS protection, and a single console for managing records as we deploy to Fly.io / GCP / wherever.

**Time:** ~30 minutes hands-on; DNS propagation takes 2-24 hours.

**You do this, not me — I can't sign into your accounts.** Step-by-step below.

## Domains in scope

- `versawiki.com` — Primary. Marketing site + app + API.
- `versawiki.ai` — Vanity for AI positioning. 301-redirect to .com for now.
- `versawiki.net` — Redirect to .com.
- `versawiki.org` — Redirect to .com.

## Recommended record plan (after migration)

```
versawiki.com               A     <Fly.io anycast IP>     (app, after deploy)
www.versawiki.com           CNAME versawiki.com
api.versawiki.com           CNAME <fly-app>.fly.dev
mcp.versawiki.com           CNAME <fly-app>.fly.dev      (LLM-facing MCP endpoint)
docs.versawiki.com          CNAME <docs-host>
status.versawiki.com        CNAME <statuspage>
orchestrator.versawiki.com  A     <GCP VM IP>            (Claude SDK orchestrator)
support.versawiki.com       CNAME <support-agent-host>
MX                          versawiki.com -> Cloudflare email routing -> josh@gmail
```

The vanity domains (.ai .net .org) get a single A record each pointing at a Cloudflare Worker that 301s to `https://versawiki.com$REQUEST_URI`.

## Step-by-step

### 1. Sign up at Cloudflare (free)

https://dash.cloudflare.com/sign-up — use the same email as your Namecheap account if convenient. Free tier is fine for everything in this spec.

### 2. Add each domain

In the Cloudflare dashboard:

1. Click "Add a Site"
2. Enter `versawiki.com` (then repeat for .ai, .net, .org)
3. Pick the Free plan
4. Cloudflare scans existing Namecheap DNS records and copies them in. Verify the imported list looks reasonable.
5. Cloudflare gives you TWO nameservers like `ada.ns.cloudflare.com` and `kirk.ns.cloudflare.com`. **Copy these — they're different per domain.**

### 3. Update Namecheap to use Cloudflare nameservers

1. Log in to Namecheap → Domain List → Manage (next to each domain)
2. NAMESERVERS section → change from "Namecheap Web Hosting DNS" or "Namecheap Default" to **Custom DNS**
3. Paste the two Cloudflare nameservers Cloudflare gave you for THAT domain
4. Click the green checkmark to save
5. Repeat for all four domains

### 4. Wait for propagation

Cloudflare emails you when each domain is "Active" (usually 1-4 hours; can be up to 48). You can hurry it along by clicking "Recheck nameservers" in the Cloudflare overview page.

### 5. Turn on the right Cloudflare defaults

In each domain's Cloudflare console:

- **SSL/TLS** → mode = **Full (strict)** once your origin servers have certs; **Flexible** is acceptable as a stopgap but insecure long-term. (Set to Full once Fly.io / origin is up.)
- **SSL/TLS → Edge Certificates** → "Always Use HTTPS" = ON
- **SSL/TLS → Edge Certificates** → "Minimum TLS Version" = 1.2
- **Speed → Optimization** → Auto Minify (HTML/CSS/JS) = ON
- **Caching → Configuration** → Browser Cache TTL = 4 hours (default)
- **Security → Settings** → Security Level = Medium
- **Security → Bots** → Bot Fight Mode = ON (free tier)
- **Email → Email Routing** → Enable, route `support@versawiki.com`, `josh@versawiki.com`, `hello@versawiki.com` → your real inbox (Gmail/iCloud/whatever)

### 6. Add the .ai/.net/.org redirect Worker

```javascript
// Cloudflare Worker: redirect-to-com
addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  url.hostname = "versawiki.com";
  event.respondWith(Response.redirect(url.toString(), 301));
});
```

Bind the Worker to a route on each of .ai/.net/.org: `*versawiki.ai/*`, `*versawiki.net/*`, `*versawiki.org/*`.

### 7. Verify

```bash
dig versawiki.com NS +short          # should show *.ns.cloudflare.com
curl -I https://versawiki.com         # should redirect, eventually return 200
curl -I https://versawiki.ai          # should 301 to .com
```

## What this unlocks

- Free wildcard SSL on `*.versawiki.com` (you'll lean on this for tenant-scoped subdomains)
- DDoS protection on the apex domains
- Page Rules + Workers for things like `api.versawiki.com/v1/*` → `auth-required` headers
- A single console to point at Fly.io when M1 ships, GCP when the orchestrator lives there, Vercel if we ever use it for the marketing site
- Email routing so `support@versawiki.com` works without standing up a Gmail Workspace yet

## Don't do this yet

- Don't enable Cloudflare's "Under Attack Mode" — that breaks API calls
- Don't enable Rocket Loader — it breaks React hydration
- Don't enable Mirage / Polish — image-heavy features we don't need
- Don't set up Cloudflare Tunnels for the GCP VM yet (use direct IP until the orchestrator ships; tunnels later for security)

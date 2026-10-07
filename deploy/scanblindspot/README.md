# scanblindspot.com proxy

A Vercel project with no code: `vercel.json` rewrites every path on
https://scanblindspot.com to the Blindspot Hugging Face Space
(https://yashwrites-blindspot.hf.space/) at the root path, so the app is
served from its own domain. Tracking and feedback still go to the shared
Cloudflare Worker, which allows this origin.

## Deploy

```sh
cd deploy/scanblindspot
vercel link --yes --project scanblindspot   # scope: ysunkara-27s-projects
vercel --prod --yes
```

## Custom domain (one-time, in the Vercel dashboard)

Project **scanblindspot** → Settings → Domains: add `scanblindspot.com`
and `www.scanblindspot.com` (set one to redirect to the other; Vercel
offers this when adding the second). Then point DNS at the registrar as
Vercel shows: apex `A 76.76.21.21`, `www CNAME cname.vercel-dns.com`.
Vercel issues the certificate automatically once DNS resolves.

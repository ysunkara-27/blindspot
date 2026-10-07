# readblindspot.com proxy

A Vercel project with no code: `vercel.json` rewrites every path on
https://readblindspot.com to the Blindspot Hugging Face Space
(https://yashwrites-blindspot.hf.space/) at the root path, so the app is
served from its own domain. Tracking and feedback still go to the shared
Cloudflare Worker, which allows this origin.

## Deploy

```sh
cd deploy/readblindspot
vercel link --yes --project readblindspot   # scope: ysunkara-27s-projects
vercel --prod --yes
```

## Custom domain (one-time, in the Vercel dashboard)

Project **readblindspot** → Settings → Domains: add `readblindspot.com`
and `www.readblindspot.com` (set one to redirect to the other; Vercel
offers this when adding the second). Then point DNS at the registrar as
Vercel shows: apex `A 76.76.21.21`, `www CNAME cname.vercel-dns.com`.
Vercel issues the certificate automatically once DNS resolves.

## 2026-10-25

### Performance

- Removed the Python cover-image optimizer, its API endpoint, and Pillow production dependency. Covers now load directly from stored ComicVine artwork URLs, using ComicVine's CDN instead of Vercel Fluid Compute.
- Roll v2 now exposes provider-hosted cover URLs rather than the retired same-origin image proxy.

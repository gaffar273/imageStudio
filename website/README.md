# AGS Labs website

The AGS Labs product catalog lives at https://agslabs.tech. Each product has its own page, downloads, guide and GitHub support links.

| Page | URL |
| --- | --- |
| Studio homepage | `/` |
| Downloads | `/downloads/` |
| Support | `/support/` |
| Image Studio | `/product/image-studio` |
| GlideYT | `/product/glideYT` |
| Image Studio privacy | `/privacy/` |

Run `npm ci` then `npm run dev` from this directory. `npm run build` type-checks the project and builds the static pages into `dist/`. Use `npm run preview` for the production build.

The Vercel project uses the `website` root of `gaffar273/imageStudio` and deploys from `main`. The Vite build has a separate HTML entry for each product so direct visits and link previews have the correct metadata. The short URL `/glideYT` redirects to its product page.

Add product names, artwork, descriptions and walkthrough links in `public/product-catalog.json`. The Products dropdown and homepage share this catalog. For a new product landing page, add its HTML entry, and register the new product HTML input in `vite.config.ts`. Image Studio reads its own GitHub releases. GlideYT serves its Windows installer from a checksum-specific directory under `public/downloads/glideyt/`. When updating it, change the download links and the SHA-256 value on the Windows help page. The Android APK comes from the latest GlideYT GitHub release.

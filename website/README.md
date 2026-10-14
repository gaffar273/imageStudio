# Image Studio website

The landing page for Image Studio by AGS Labs, served at https://agslabs.tech.

React 19, TypeScript, Vite and Tailwind CSS 4. Components from shadcn/ui's registry and Magic UI
(Marquee, Animated Beam, Number Ticker, Blur Fade, Border Beam in `src/components/ui/`), Motion for
animation, Lenis for smooth scrolling, Radix UI (accordion), react-compare-slider,
yet-another-react-lightbox, Lucide icons and Sonner. Type: Geist with Instrument Serif accents.

```powershell
npm ci
npm run dev       # http://127.0.0.1:5173
npm run build     # static site in dist/
npm run preview   # serve dist/ on http://127.0.0.1:4173
```

`dist/` is a plain static site with relative URLs, so it works at a domain root and at a sub-path.

## Hosting

Hosted on Vercel: import the `gaffar273/imageStudio` repository and set **Root Directory** to
`website`. Vercel detects Vite (build `npm run build`, output `dist`) and redeploys on every push to
`main`. Add `agslabs.tech` under the project's **Domains** and enter the DNS records Vercel shows at
the domain's registrar.

## Downloads follow the GitHub release

The page asks the GitHub API for the newest published release of `gaffar273/imageStudio`
(`src/hooks/useRelease.ts`). Until one exists it shows "coming soon" and offers to watch the
repository. Once a release is published with a `.exe` (and optionally a `.tar.gz`) attached, every
download button links to that file with its real size and version, with no change to the site.

## Content

- Names and links: `src/site.ts`. Pictures, prompts, timings, pipeline names: `src/content.ts`.
- Images: `public/media/`. They are real app screenshots and real library pictures; the model and
  time shown with each picture come from its saved metadata.

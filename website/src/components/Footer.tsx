import { ArrowDownToLine, Eye } from 'lucide-react'
import { Button, Em, GitHubIcon, Logo } from './ui'
import { useRelease } from '@/hooks/useRelease'
import { links, nav, ORG } from '@/site'
import { byId } from '@/content'

const strip = ['seaside', 'fox', 'umbrella', 'chef', 'lake', 'market', 'lighthouse'].map(byId)

export function Footer() {
  const release = useRelease()
  const windows = release.state === 'ready' ? release.windows : undefined
  return (
    <footer className="px-3 pb-3 sm:px-4 sm:pb-4">
      <div className="relative overflow-hidden rounded-[34px] bg-ink text-white">
        {/* a row of real pictures, like prints pinned on a line */}
        <div className="flex justify-center gap-3 overflow-hidden pt-10 opacity-90 [mask-image:linear-gradient(to_right,transparent,black_15%,black_85%,transparent)]">
          {strip.map((p, i) => (
            <img
              key={p.id}
              src={`media/gallery-${p.id}.webp`}
              alt=""
              loading="lazy"
              style={{ rotate: `${(i % 2 ? 1 : -1) * (2 + (i % 3))}deg` }}
              className="size-[92px] shrink-0 rounded-lg border-[3px] border-white/90 object-cover shadow-lg sm:size-[120px]"
            />
          ))}
        </div>
        <div className="px-6 pt-12 pb-14 text-center sm:px-10">
          <h2 className="mx-auto max-w-[16ch] text-[40px] leading-[1.02] font-semibold tracking-[-0.04em] sm:text-[64px]">
            Your next picture is <Em>one sentence away.</Em>
          </h2>
          <div className="mt-9 flex flex-wrap justify-center gap-3">
            {windows ? (
              <Button variant="primary" size="lg" href={windows.url}>
                <ArrowDownToLine className="size-[18px]" /> Download for Windows
              </Button>
            ) : (
              <Button size="lg" href={links.watch} target="_blank" rel="noreferrer" className="border-white bg-white text-ink hover:border-white">
                <Eye className="size-[18px]" /> Watch for the release
              </Button>
            )}
            <Button
              size="lg"
              href={links.repo}
              target="_blank"
              rel="noreferrer"
              className="border-white/20 bg-white/5 text-white shadow-none hover:border-white/50"
            >
              <GitHubIcon className="size-4" /> View the code
            </Button>
          </div>
        </div>

        <div className="grid gap-8 border-t border-white/10 px-6 py-10 sm:grid-cols-[minmax(0,1.5fr)_repeat(2,minmax(0,1fr))] sm:px-10">
          <div className="[&_.text-muted]:text-white/55">
            <Logo org={ORG.name} />
            <p className="mt-4 max-w-[36ch] text-[14px] leading-relaxed text-white/60">
              A desktop app for making and editing pictures with models that run on your own graphics card.
            </p>
          </div>
          <div>
            <h3 className="text-[13px] text-white/45">On this page</h3>
            <ul className="mt-3 space-y-2">
              {nav.map((n) => (
                <li key={n.id}>
                  <a href={`#${n.id}`} className="text-[14px] text-white/80 transition-colors hover:text-white">
                    {n.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="text-[13px] text-white/45">Project</h3>
            <ul className="mt-3 space-y-2">
              {[
                ['Source code', links.repo],
                ['Releases', links.releases],
                ['Report a problem', links.issues],
                [ORG.name, ORG.url],
              ].map(([label, href]) => (
                <li key={label}>
                  <a href={href} target="_blank" rel="noreferrer" className="text-[14px] text-white/80 transition-colors hover:text-white">
                    {label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/10 px-6 py-5 text-[13px] text-white/45 sm:px-10">
          <span>
            © {new Date().getFullYear()} {ORG.name}
          </span>
          <a href={ORG.url} className="transition-colors hover:text-white">
            agslabs.tech
          </a>
        </div>
      </div>
    </footer>
  )
}

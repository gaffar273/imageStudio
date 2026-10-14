import { useState } from 'react'
import { ArrowDownToLine, ArrowUpRight, Check, Copy, Cpu, Eye, HardDrive, MemoryStick, Monitor, ShieldAlert, Terminal, Wifi } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { BorderBeam } from '@/components/ui/border-beam'
import { AppIcon, Button, Em, GitHubIcon, Intro, WindowsIcon } from './ui'
import { useRelease, windowsDownload } from '@/hooks/useRelease'
import { clone, facts, links } from '@/site'

const needs = [
  { icon: Monitor, k: 'System', v: 'Windows 10 or 11, 64-bit' },
  { icon: Cpu, k: 'Graphics', v: 'NVIDIA, 8 GB of video memory', note: 'or cloud mode with a key' },
  { icon: MemoryStick, k: 'Memory', v: '16 GB of RAM' },
  { icon: HardDrive, k: 'Disk', v: `${facts.engine} engine + 7 to 17 GB per model` },
  { icon: Wifi, k: 'Internet', v: 'Only to download, or for cloud' },
]

function CopyLine({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          setDone(true)
          toast.success('Copied')
          window.setTimeout(() => setDone(false), 1800)
        } catch {
          toast.error('Could not copy. Select the text instead.')
        }
      }}
      className="group flex w-full items-center gap-3 rounded-xl border border-line bg-[#111113] px-3.5 py-3 text-left font-mono text-[12.5px] text-white/90 transition-colors hover:border-ink"
    >
      <span className="min-w-0 flex-1 truncate">
        <span className="text-white/40 select-none">$ </span>
        {text}
      </span>
      {done ? <Check className="size-4 shrink-0 text-emerald-400" /> : <Copy className="size-4 shrink-0 text-white/50 group-hover:text-white" />}
    </button>
  )
}

export function Download() {
  const release = useRelease()
  const ready = release.state === 'ready'
  const windows = windowsDownload(release)
  const linux = ready ? release.linux : undefined
  const page = ready ? release.page : release.state === 'unknown' ? links.latest : links.releases

  return (
    <section id="download" className="scroll-mt-24 px-4 py-24 sm:px-5 sm:py-32">
      <Intro
        badge={
          <>
            <ArrowDownToLine className="size-3.5 text-accent" /> Download
          </>
        }
        title={
          <>
            Get Image Studio <Em>for Windows.</Em>
          </>
        }
        lead="A small installer with its own Python. On first start it sets up the engine and the models you pick."
      />

      <div className="mx-auto mt-14 grid max-w-[1180px] grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        {/* Windows */}
        <div className="relative overflow-hidden rounded-[30px] border border-line bg-card p-7 shadow-float sm:p-10">
          <div className="pointer-events-none absolute -top-24 -right-24 size-[360px] rounded-full bg-[radial-gradient(closest-side,rgb(37_99_235/0.14),transparent)]" />
          {windows && <BorderBeam size={120} duration={9} colorFrom="#2563eb" colorTo="#93c5fd" borderWidth={1.5} />}
          <div className="relative flex items-center gap-4">
            <AppIcon className="size-14" />
            <div>
              <div className="flex items-center gap-2 text-[20px] font-semibold tracking-[-0.02em]">
                <WindowsIcon className="size-4 text-accent" /> Windows
              </div>
              <div className="mt-1 text-[14px] text-muted">
                {release.state === 'loading' && 'Checking GitHub for the latest release…'}
                {release.state === 'none' && 'Installer coming soon'}
                {release.state === 'unknown' && 'The latest version, from GitHub Releases'}
                {ready && windows && `Version ${release.version} · ${windows.size} · ${release.date}`}
                {ready && !windows && `Version ${release.version} has no Windows installer attached`}
              </div>
            </div>
            <span
              className={cn(
                'ml-auto hidden rounded-full px-3 py-1 text-[12.5px] font-medium sm:inline-flex',
                windows ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700',
              )}
            >
              {windows ? 'Available' : release.state === 'loading' ? 'Checking' : 'Coming soon'}
            </span>
          </div>

          {windows ? (
            <>
              <div className="relative mt-8 flex flex-wrap gap-3">
                <Button variant="primary" size="lg" href={windows.url}>
                  <ArrowDownToLine className="size-[18px]" /> Download installer
                </Button>
                <Button size="lg" href={page} target="_blank" rel="noreferrer">
                  Release notes <ArrowUpRight className="size-4" />
                </Button>
              </div>
              {windows.name && <p className="relative mt-3 font-mono text-[12px] text-muted">{windows.name}</p>}
              <div className="relative mt-7 flex gap-3 rounded-2xl bg-amber-50/80 px-4 py-3.5 text-[13.5px] leading-relaxed text-body">
                <ShieldAlert className="mt-0.5 size-4 shrink-0 text-amber-600" />
                <div>
                  <p>The installer is new and not code-signed yet, so Windows checks with you twice:</p>
                  <ol className="mt-1.5 list-decimal space-y-1 pl-4">
                    <li>
                      If Edge says it <span className="text-ink">isn’t commonly downloaded</span>: open the{' '}
                      <strong className="font-semibold text-ink">⋯</strong> menu next to the file, choose{' '}
                      <strong className="font-semibold text-ink">Keep</strong>, then{' '}
                      <strong className="font-semibold text-ink">Show more</strong> and{' '}
                      <strong className="font-semibold text-ink">Keep anyway</strong>.
                    </li>
                    <li>
                      When you run it: <strong className="font-semibold text-ink">More info</strong>, then{' '}
                      <strong className="font-semibold text-ink">Run anyway</strong>.
                    </li>
                  </ol>
                </div>
              </div>
            </>
          ) : (
            <>
              <p className="relative mt-8 max-w-[52ch] text-[16px] leading-relaxed text-body">
                The first Windows installer is being prepared for GitHub Releases. Watch the repository and GitHub
                will tell you the moment it is published. You can run the app from source today.
              </p>
              <div className="relative mt-7 flex flex-wrap gap-3">
                <Button variant="dark" size="lg" href={links.watch} target="_blank" rel="noreferrer">
                  <Eye className="size-[18px]" /> Watch on GitHub
                </Button>
                <Button size="lg" href={links.source} target="_blank" rel="noreferrer">
                  <GitHubIcon className="size-4" /> Run from source
                </Button>
              </div>
              <p className="relative mt-4 text-[13px] text-muted">
                On GitHub: <span className="text-ink">Watch → Custom → Releases</span> to get only release emails.
              </p>
            </>
          )}
        </div>

        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4">
          <div className="rounded-[30px] border border-line bg-card p-7 shadow-card">
            <div className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-xl bg-tint">
                <Terminal className="size-5" />
              </span>
              <div>
                <div className="text-[17px] font-semibold">Linux</div>
                <div className="text-[13px] text-muted">x86-64 tarball · preview</div>
              </div>
              {linux ? (
                <Button size="sm" href={linux.url} className="ml-auto">
                  <ArrowDownToLine className="size-4" /> {linux.size}
                </Button>
              ) : (
                <span className="ml-auto rounded-full bg-tint px-3 py-1 text-[12.5px] text-muted">Not yet</span>
              )}
            </div>
            <p className="mt-4 text-[14px] leading-relaxed text-body">
              {linux ? (
                <>
                  Unpack it and run <code className="rounded bg-tint px-1.5 py-0.5 font-mono text-[12.5px]">./install.sh</code>.
                  It has seen little testing so far, so reports are welcome.
                </>
              ) : (
                'A Linux build is not in this release yet. Until then, run it from source.'
              )}
            </p>
          </div>
          <div className="rounded-[30px] border border-line bg-card p-7 shadow-card">
            <div className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-xl bg-tint">
                <GitHubIcon className="size-5" />
              </span>
              <div>
                <div className="text-[17px] font-semibold">From source</div>
                <div className="text-[13px] text-muted">Python 3.10 or newer</div>
              </div>
              <a
                href={links.source}
                target="_blank"
                rel="noreferrer"
                className="ml-auto flex items-center gap-1 text-[13.5px] font-medium text-accent hover:text-accent-ink"
              >
                Guide <ArrowUpRight className="size-3.5" />
              </a>
            </div>
            <div className="mt-4">
              <CopyLine text={clone} />
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto mt-4 grid max-w-[1180px] grid-cols-2 gap-px overflow-hidden rounded-[26px] border border-line bg-line sm:grid-cols-3 lg:grid-cols-5">
        {needs.map((n) => (
          <div key={n.k} className="bg-card p-5">
            <n.icon className="size-[18px] text-muted" strokeWidth={1.8} />
            <div className="mt-3 text-[12.5px] text-muted">{n.k}</div>
            <div className="mt-1 text-[14px] leading-snug font-medium">{n.v}</div>
            {n.note && <div className="mt-0.5 text-[12.5px] text-muted">{n.note}</div>}
          </div>
        ))}
        <div className="bg-card p-5 sm:hidden" />
      </div>
    </section>
  )
}

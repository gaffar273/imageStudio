import * as Accordion from '@radix-ui/react-accordion'
import { ArrowUpRight, Bug, CircleHelp, LifeBuoy, Plus } from 'lucide-react'
import type { ReactNode } from 'react'
import { Em, Intro } from './ui'
import { facts, links } from '@/site'

const Path = ({ children }: { children: ReactNode }) => (
  <code className="rounded-md bg-tint px-1.5 py-0.5 font-mono text-[12.5px] [overflow-wrap:anywhere] text-ink">{children}</code>
)

const faq: { q: string; a: ReactNode }[] = [
  {
    q: 'How do I get new versions?',
    a: (
      <>
        Every version is published on{' '}
        <a href={links.releases} target="_blank" rel="noreferrer" className="text-accent underline-offset-2 hover:underline">
          GitHub Releases
        </a>
        , and the download buttons on this page always point to the newest one. To get an email when one comes out,
        watch the repository: <strong>Watch</strong>, then <strong>Custom</strong>, then <strong>Releases</strong>.
      </>
    ),
  },
  {
    q: 'Edge says the installer “isn’t commonly downloaded”. Is that expected?',
    a: (
      <>
        Yes. Microsoft SmartScreen warns about any installer that is new and not code-signed yet, until enough people
        have downloaded it. In Edge, open the <strong>⋯</strong> menu next to the download, choose <strong>Keep</strong>,
        then <strong>Show more</strong> and <strong>Keep anyway</strong>. When you run it and Windows says “Windows
        protected your PC”, choose <strong>More info</strong>, then <strong>Run anyway</strong>. It installs for your
        user only. You can check the file against the SHA-256 in the{' '}
        <a href={links.latest} target="_blank" rel="noreferrer" className="text-accent underline-offset-2 hover:underline">
          release notes
        </a>
        .
      </>
    ),
  },
  {
    q: 'I don’t have an NVIDIA graphics card. Can I still use it?',
    a: (
      <>
        Yes. In Settings → Models choose <strong>Engine in cloud mode</strong> (about {facts.cloudEngine}), then connect
        OpenAI, Gemini, fal.ai or Replicate under Settings → Providers. Create and Edit run through that service. You can
        add the full engine later.
      </>
    ),
  },
  {
    q: 'Where are my pictures, models and settings kept?',
    a: (
      <ul className="space-y-2">
        <li>
          Pictures: <Path>Pictures\Image Studio</Path>
        </li>
        <li>
          Models: <Path>%LOCALAPPDATA%\Image Studio\models</Path>
        </li>
        <li>
          Settings: <Path>%APPDATA%\Image Studio\settings.json</Path>
        </li>
        <li className="text-muted">
          Move them with <Path>IMAGE_STUDIO_WORK</Path> and <Path>IMAGE_STUDIO_LIBRARY</Path>.
        </li>
      </ul>
    ),
  },
  {
    q: 'Are my API keys safe?',
    a: (
      <>
        Keys are kept in <Path>credentials.json</Path>, encrypted for your Windows account, and only ever sent to their
        own service. They never go into <Path>settings.json</Path>.
      </>
    ),
  },
  {
    q: 'A game needs my graphics card. How do I free it?',
    a: 'The engine card at the bottom of the sidebar shows live GPU and RAM use. Its memory button unloads every model. Closing the window stops the engine too.',
  },
  {
    q: 'Do I need PhotoCraft or Krita?',
    a: 'No. Create and Edit work on their own. PhotoCraft studio and the Krita canvas light up when those apps are found on your PC.',
  },
  {
    q: 'How do I uninstall it?',
    a: 'From Apps in Windows Settings. The app and the engine’s libraries are removed; your models, pictures and settings stay.',
  },
]

const docs = [
  { title: 'README', text: 'Install, screens, files and commands', href: links.readme },
  { title: 'PhotoCraft assistant', text: 'How a request becomes commands', href: links.doc('docs/photocraft-assistant.md') },
  { title: 'Pipeline engine', text: 'Why every edit is coded', href: links.doc('docs/pipeline-engine.md') },
  { title: `All ${facts.pipelines} pipelines`, text: 'The full catalogue', href: links.doc('docs/pipelines.md') },
  { title: 'Models and training', text: 'What runs, and memory use', href: links.doc('docs/model-guide.md') },
  { title: 'Architecture', text: 'App, engine and API', href: links.doc('docs/architecture.md') },
]

export function Help() {
  return (
    <section id="help" className="scroll-mt-24 border-t border-line bg-card px-4 py-24 sm:px-5 sm:py-32">
      <Intro
        badge={
          <>
            <LifeBuoy className="size-3.5 text-accent" /> Help and resources
          </>
        }
        title={
          <>
            Questions, <Em>answered.</Em>
          </>
        }
      />
      <div className="mx-auto mt-14 grid max-w-[1180px] grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
        <Accordion.Root type="single" collapsible defaultValue="q-0" className="space-y-2.5">
          {faq.map((f, i) => (
            <Accordion.Item
              key={f.q}
              value={`q-${i}`}
              className="overflow-hidden rounded-2xl border border-line bg-bg/50 transition-colors data-[state=open]:border-line-strong data-[state=open]:bg-card data-[state=open]:shadow-card"
            >
              <Accordion.Header>
                <Accordion.Trigger className="group flex w-full items-center gap-4 px-5 py-4 text-left">
                  <span className="flex-1 text-[15.5px] font-medium tracking-[-0.01em]">{f.q}</span>
                  <span className="grid size-7 shrink-0 place-items-center rounded-full border border-line bg-card transition-transform duration-300 group-data-[state=open]:rotate-45">
                    <Plus className="size-3.5" />
                  </span>
                </Accordion.Trigger>
              </Accordion.Header>
              <Accordion.Content className="overflow-hidden data-[state=closed]:animate-[collapse_220ms_ease-out] data-[state=open]:animate-[expand_260ms_ease-out]">
                <div className="px-5 pb-5 text-[14.5px] leading-[1.7] text-body [&_strong]:font-semibold [&_strong]:text-ink">{f.a}</div>
              </Accordion.Content>
            </Accordion.Item>
          ))}
        </Accordion.Root>

        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-4">
            {[
              { icon: Bug, title: 'Report a problem', text: 'Say what you did and what happened.', href: links.issues },
              { icon: CircleHelp, title: 'Ask a question', text: 'How to do something, or an idea.', href: links.question },
            ].map((c) => (
              <a
                key={c.title}
                href={c.href}
                target="_blank"
                rel="noreferrer"
                className="group flex flex-col rounded-[22px] border border-line bg-bg/50 p-5 transition-all hover:-translate-y-0.5 hover:border-line-strong hover:bg-card hover:shadow-card"
              >
                <c.icon className="size-5" strokeWidth={1.8} />
                <span className="mt-4 flex items-center gap-1 text-[15px] font-semibold">
                  {c.title}
                  <ArrowUpRight className="size-3.5 text-muted transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                </span>
                <span className="mt-1 text-[13px] leading-snug text-muted">{c.text}</span>
              </a>
            ))}
          </div>
          <div className="rounded-[22px] border border-line p-2">
            <div className="px-3 pt-3 pb-2 text-[13px] font-medium text-muted">Documentation</div>
            {docs.map((d) => (
              <a
                key={d.title}
                href={d.href}
                target="_blank"
                rel="noreferrer"
                className="group flex items-center gap-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-tint"
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-[14.5px] font-medium">{d.title}</span>
                  <span className="block text-[12.5px] text-muted">{d.text}</span>
                </span>
                <ArrowUpRight className="size-4 text-faint transition-all group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-ink" />
              </a>
            ))}
          </div>
          <p className="px-1 text-[13px] leading-relaxed text-muted">
            When something breaks, the engine log at <Path>%LOCALAPPDATA%\Image Studio\logs\engine.log</Path> usually says
            why. Attach it to the report.
          </p>
        </div>
      </div>
    </section>
  )
}

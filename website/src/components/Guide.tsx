import { motion } from 'motion/react'
import { BookOpenText, Download, KeyRound, PackageOpen, Sparkles } from 'lucide-react'
import { Em, Intro } from './ui'
import { facts } from '@/site'

const steps = [
  {
    icon: Download,
    title: 'Install',
    where: 'Setup.exe',
    text: 'Run the installer. It installs for your user only: no administrator prompt, no account.',
  },
  {
    icon: PackageOpen,
    title: 'Set up the engine',
    where: 'Settings → Models',
    text: `The first start opens Models. One click on Engine installs PyTorch and the model libraries (about ${facts.engine}). No NVIDIA card? Pick Engine in cloud mode (about ${facts.cloudEngine}).`,
  },
  {
    icon: KeyRound,
    title: 'Add models or a key',
    where: 'Models · Providers',
    text: 'Install the models you want; downloads resume if the connection drops. Or paste an API key under Providers to work in the cloud.',
  },
  {
    icon: Sparkles,
    title: 'Describe it',
    where: 'Create · Edit · PhotoCraft',
    text: 'Write a picture in Create, or drop a photo on Edit and say what to change. For a full retouch, describe every change at once in PhotoCraft.',
  },
]

const shortcuts = [
  [['Ctrl', 'Enter'], 'Generate, apply, or plan'],
  [['Ctrl', 'V'], 'Paste a photo to edit'],
  [['Ctrl', 'Z'], 'Undo, or take back a painted stroke'],
  [['Ctrl', 'O'], 'Open a file in PhotoCraft'],
] as const

const tips = [
  ['Say how much', '“A little warmer” and “much warmer” are different edits.'],
  ['Name what stays', '“Keep the person unchanged” is read and checked.'],
  ['Mark an area', 'Brush or lasso a region and the request stays inside it.'],
]

export function Guide() {
  return (
    <section id="guide" className="scroll-mt-24 border-y border-line bg-card px-4 py-24 sm:px-5 sm:py-32">
      <Intro
        badge={
          <>
            <BookOpenText className="size-3.5 text-accent" /> How to use
          </>
        }
        title={
          <>
            Four steps <Em>to the first picture.</Em>
          </>
        }
      />
      <ol className="relative mx-auto mt-14 grid max-w-[1180px] gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {steps.map((s, i) => (
          <motion.li
            key={s.title}
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-60px' }}
            transition={{ duration: 0.55, delay: i * 0.08, ease: [0.22, 1, 0.36, 1] }}
            className="relative flex flex-col rounded-[26px] border border-line bg-bg/60 p-6"
          >
            <div className="flex items-center justify-between">
              <span className="relative z-10 grid size-12 place-items-center rounded-2xl border border-line bg-card shadow-card">
                <s.icon className="size-5" strokeWidth={1.8} />
              </span>
              <span className="serif text-[56px] leading-none text-line-strong">{i + 1}</span>
            </div>
            <h3 className="mt-6 text-[19px] font-semibold tracking-[-0.02em]">{s.title}</h3>
            <span className="mt-1.5 w-fit rounded-full bg-accent-soft px-2.5 py-0.5 text-[12px] font-medium text-accent-ink">{s.where}</span>
            <p className="mt-3 text-[14.5px] leading-relaxed text-body">{s.text}</p>
          </motion.li>
        ))}
      </ol>

      <div className="mx-auto mt-4 grid max-w-[1180px] grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div className="rounded-[26px] border border-line p-6">
          <h3 className="text-[15px] font-semibold">Keyboard shortcuts</h3>
          <ul className="mt-4 grid gap-3 sm:grid-cols-2">
            {shortcuts.map(([keys, what]) => (
              <li key={what} className="flex items-center gap-3">
                <span className="flex shrink-0 items-center gap-1">
                  {keys.map((k) => (
                    <kbd key={k} className="kbd">
                      {k}
                    </kbd>
                  ))}
                </span>
                <span className="text-[13.5px] text-body">{what}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-[26px] border border-line p-6">
          <h3 className="text-[15px] font-semibold">Writing a good request</h3>
          <ul className="mt-4 space-y-3">
            {tips.map(([k, v]) => (
              <li key={k} className="text-[13.5px] leading-snug text-body">
                <span className="font-semibold text-ink">{k}.</span> {v}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  )
}

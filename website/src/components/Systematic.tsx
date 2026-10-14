import { useEffect, useRef, useState, type ReactNode } from 'react'
import { AnimatePresence, motion, useInView } from 'motion/react'
import { ReactCompareSlider, ReactCompareSliderHandle, ReactCompareSliderImage } from 'react-compare-slider'
import { Check, Eye, Layers, ListChecks, ScanSearch, SquareStack, TerminalSquare, TextSearch, Workflow } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Em, Intro } from './ui'
import { facts } from '@/site'

/*
 * One real PhotoCraft run (2026-10-15, laptop RTX 4060, bundled Qwen3.5-9B planner): the request,
 * the plan, the commands and the checks below are what the app returned, unedited.
 */

const parts = [
  { text: 'Make the room much less yellow', tone: 'c1' },
  { text: ', ' },
  { text: 'brighten the dog', tone: 'c2' },
  { text: ', ' },
  { text: 'crop to 16:9', tone: 'c3' },
  { text: ' and ' },
  { text: "add 'Best friends' at the top in a bold white serif with a shadow", tone: 'c4' },
  { text: '. ' },
  { text: 'Keep the cat exactly as it is.', tone: 'keep' },
] as const

type Tone = 'c1' | 'c2' | 'c3' | 'c4' | 'keep'
const tones: Record<Tone, { dot: string; mark: string; box: string; tag: string }> = {
  c1: { dot: 'bg-[#d97706]', mark: 'bg-[#fdf1dc] text-[#92400e]', box: 'border-[#f59e0b]', tag: 'bg-[#f59e0b] text-[#3b1d00]' },
  c2: { dot: 'bg-[#7c3aed]', mark: 'bg-[#f1eafe] text-[#5b21b6]', box: 'border-[#a78bfa]', tag: 'bg-[#a78bfa] text-[#1e0b4b]' },
  c3: { dot: 'bg-[#0d9488]', mark: 'bg-[#e0f5f2] text-[#115e59]', box: '', tag: '' },
  c4: { dot: 'bg-[#2563eb]', mark: 'bg-[#eaf0fe] text-[#1e40af]', box: '', tag: '' },
  keep: { dot: 'bg-[#16a34a]', mark: 'bg-[#e6f6ec] text-[#166534]', box: '', tag: '' },
}

const changes: { tone: Tone; quote: string; pipeline: string; built: string }[] = [
  {
    tone: 'c1',
    quote: 'Make the room much less yellow',
    pipeline: 'temperature',
    built: 'Select everything else, then less temperature on the background, on its own masked layer',
  },
  { tone: 'c2', quote: 'brighten the dog', pipeline: 'brightness', built: 'More brightness on the dog, on a masked layer' },
  { tone: 'c3', quote: 'crop to 16:9', pipeline: 'crop_aspect', built: 'Crop to 16:9 (1216 × 684)' },
  { tone: 'c4', quote: "add 'Best friends' at the top…", pipeline: 'add_text', built: 'Add “Best friends”: 51.3 pt, top, white, Georgia bold' },
]

// Boxes the grounder returned, as a share of the 1216 × 832 picture.
const foreground = [
  [1.4, 20.9, 40.2, 51.2],
  [53.6, 63.9, 40.0, 31.3],
  [0, 67.5, 53.8, 32.5],
  [55.4, 11.4, 44.6, 84.7],
]
const dog = [53.6, 63.9, 40.0, 31.3]

const commands: { tone: Tone; cmd: string; args?: string }[] = [
  { tone: 'c1', cmd: 'studio.select_outline', args: 'everything in the foreground, 4 boxes' },
  { tone: 'c1', cmd: 'studio.require_selection', args: 'it was found' },
  { tone: 'c1', cmd: 'select.inverse' },
  { tone: 'c1', cmd: 'filter.cameraRaw', args: 'temperature −60, masked layer' },
  { tone: 'c1', cmd: 'select.deselect' },
  { tone: 'c2', cmd: 'studio.select_outline', args: 'the dog' },
  { tone: 'c2', cmd: 'studio.require_selection', args: 'the dog was found' },
  { tone: 'c2', cmd: 'layer.newAdjustmentLayer.brightnessContrast', args: 'brightness +25' },
  { tone: 'c2', cmd: 'layer.renameLayer', args: '“More brightness · the dog”' },
  { tone: 'c2', cmd: 'select.deselect' },
  { tone: 'c3', cmd: 'image.crop', args: 'x 0, y 74, 1216 × 684' },
  { tone: 'c4', cmd: 'studio.text', args: '“Best friends”, Georgia 700, 51.3 pt, #ffffff, shadow' },
]

const layers = [
  { name: 'Best friends', kind: 'Type · Drop Shadow', tone: 'c4' as Tone },
  { name: 'More brightness · the dog', kind: 'Brightness/Contrast · mask', tone: 'c2' as Tone },
  { name: 'Less temperature · background', kind: 'Camera Raw · mask', tone: 'c1' as Tone },
  { name: 'Photo', kind: 'Smart Object', tone: null },
]

const checks = ['Aspect ratio is 16:9 (1216 × 684)', 'Text reads exactly “Best friends”', 'Text sits at the top and fits in the picture']

const steps = [
  { icon: TextSearch, title: 'Read', text: 'The request becomes four changes and one thing to keep.' },
  { icon: ScanSearch, title: 'Find', text: 'A vision model finds what each change is about.' },
  { icon: Workflow, title: 'Choose', text: `The model only picks pipelines, from ${facts.pipelines}. Code sets every number.` },
  { icon: TerminalSquare, title: 'Build', text: 'The pipelines write exact PhotoCraft commands, in a retoucher’s order.' },
  { icon: SquareStack, title: 'Apply', text: 'Each adjustment lands on its own layer. Switch it off, or change it later.' },
  { icon: ListChecks, title: 'Check', text: 'The result is measured, and what you asked to keep is compared.' },
]

const STEP_MS = 5200

export function Systematic() {
  const [step, setStep] = useState(0)
  const [auto, setAuto] = useState(true)
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { amount: 0.4 })

  useEffect(() => {
    if (!auto || !inView) return
    const t = window.setTimeout(() => setStep((s) => (s + 1) % steps.length), STEP_MS)
    return () => window.clearTimeout(t)
  }, [auto, inView, step])

  const pick = (i: number) => {
    setAuto(false)
    setStep(i)
  }

  return (
    <section id="systematic" className="scroll-mt-24 px-4 py-24 sm:px-5 sm:py-32">
      <Intro
        badge={
          <>
            <Workflow className="size-3.5 text-accent" /> Systematic editing
          </>
        }
        title={
          <>
            Planned like a retoucher. <Em>Not redrawn.</Em>
          </>
        }
        lead={`A request becomes a plan of coded editing pipelines. They run exact commands in PhotoCraft, every adjustment lands on its own layer, and the result is measured. Nothing you didn't ask for is repainted. One real request, step by step:`}
      />

      <div ref={ref} className="mx-auto mt-12 max-w-[1180px] overflow-hidden rounded-[30px] border border-line bg-card shadow-float">
        {/* The request, colour-coded by change */}
        <div className="flex gap-3 border-b border-line px-5 py-4 sm:px-6">
          <span className="mt-1 h-fit shrink-0 self-start rounded-full bg-ink px-2.5 py-0.5 text-[12px] font-medium text-white">You</span>
          <p className="text-[15px] leading-[1.75] text-ink sm:text-[16px]">
            {parts.map((p, i) =>
              'tone' in p ? (
                <mark key={i} className={cn('rounded-md px-1 py-0.5 [box-decoration-break:clone]', tones[p.tone].mark)}>
                  {p.text}
                </mark>
              ) : (
                <span key={i}>{p.text}</span>
              ),
            )}
          </p>
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)] lg:grid-cols-[330px_minmax(0,1fr)]">
          {/* Steps */}
          <ol className="flex gap-1 overflow-x-auto border-b border-line p-2 lg:flex-col lg:overflow-visible lg:border-r lg:border-b-0 lg:p-3">
            {steps.map((s, i) => (
              <li key={s.title} className="shrink-0">
                <button
                  type="button"
                  onClick={() => pick(i)}
                  className={cn(
                    'relative flex w-full items-start gap-3 overflow-hidden rounded-2xl px-3 py-2.5 text-left transition-colors lg:py-3',
                    i === step ? 'bg-tint' : 'hover:bg-tint/60',
                  )}
                >
                  <span
                    className={cn(
                      'grid size-8 shrink-0 place-items-center rounded-xl border transition-colors',
                      i === step ? 'border-ink bg-ink text-white' : 'border-line bg-card text-body',
                    )}
                  >
                    <s.icon className="size-4" strokeWidth={1.9} />
                  </span>
                  <span className="min-w-0">
                    <span className="flex items-center gap-2 text-[14.5px] font-semibold">
                      <span className="text-faint tabular-nums">{i + 1}</span> {s.title}
                    </span>
                    <span className={cn('mt-0.5 hidden text-[13px] leading-snug text-muted lg:block', i !== step && 'lg:hidden')}>{s.text}</span>
                  </span>
                  {i === step && auto && inView && (
                    <motion.span
                      key={`bar-${step}`}
                      className="absolute bottom-0 left-0 h-[2px] bg-accent"
                      initial={{ width: '0%' }}
                      animate={{ width: '100%' }}
                      transition={{ duration: STEP_MS / 1000, ease: 'linear' }}
                    />
                  )}
                </button>
              </li>
            ))}
          </ol>

          {/* What that step looks like */}
          <div className="relative flex min-h-[520px] min-w-0 flex-col justify-center bg-tint/50 p-3 sm:p-5 lg:min-h-[640px]">
            <p className="mb-3 px-1 text-[13.5px] leading-snug text-body lg:hidden">{steps[step].text}</p>
            <AnimatePresence mode="wait">
              <motion.div
                key={step}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.28 }}
              >
                {[<ReadView />, <FindView />, <ChooseView />, <BuildView />, <ApplyView />, <CheckView />][step]}
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </div>
      <p className="mt-4 text-center text-[13px] text-muted">
        Planned in 17 s and applied in 50 s on a laptop RTX 4060, with the planner that ships with Image Studio (Qwen3.5 9B vision).
      </p>
    </section>
  )
}

function Panel({ title, aside, children }: { title: ReactNode; aside?: ReactNode; children: ReactNode }) {
  return (
    <div className="rounded-[22px] border border-line bg-card p-4 shadow-card sm:p-5">
      <div className="mb-3 flex items-center gap-2 text-[13px] font-semibold">
        {title}
        {aside && <span className="ml-auto text-[12.5px] font-normal text-muted">{aside}</span>}
      </div>
      {children}
    </div>
  )
}

function ReadView() {
  return (
    <Panel title="What the planner understood" aside="nothing runs until you press Apply">
      <ul className="space-y-2">
        {changes.map((c, i) => (
          <motion.li
            key={c.quote}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.1 + i * 0.12 }}
            className="flex items-center gap-3 rounded-xl border border-line px-3.5 py-3"
          >
            <span className={cn('size-2.5 shrink-0 rounded-full', tones[c.tone].dot)} />
            <span className="min-w-0 flex-1 text-[14px]">“{c.quote}”</span>
            <span className="shrink-0 text-[12px] text-muted">change {i + 1}</span>
          </motion.li>
        ))}
        <motion.li
          initial={{ opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.1 + changes.length * 0.12 }}
          className="flex items-center gap-3 rounded-xl border border-[#bbe5c8] bg-[#f3fbf5] px-3.5 py-3"
        >
          <span className={cn('size-2.5 shrink-0 rounded-full', tones.keep.dot)} />
          <span className="min-w-0 flex-1 text-[14px]">“Keep the cat exactly as it is”</span>
          <span className="shrink-0 text-[12px] font-medium text-[#166534]">keep</span>
        </motion.li>
      </ul>
      <p className="mt-4 text-[13px] leading-relaxed text-muted">
        Unclear parts come back as questions instead of guesses. This request had none.
      </p>
    </Panel>
  )
}

function Box({ at, className, delay }: { at: number[]; className: string; delay: number }) {
  const [x, y, w, h] = at
  return (
    <motion.span
      className={cn('absolute rounded-md border-2 border-dashed', className)}
      style={{ left: `${x}%`, top: `${y}%`, width: `${w}%`, height: `${h}%` }}
      initial={{ opacity: 0, scale: 1.06 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay, duration: 0.35 }}
    />
  )
}

function FindView() {
  return (
    <div>
      <div className="relative overflow-hidden rounded-[20px] shadow-card" style={{ aspectRatio: '1216 / 832' }}>
        <img src="media/demo-plan.webp" alt="A grey cat on a red suitcase and a brown dog under a chair" className="h-full w-full object-cover" />
        {foreground.map((b, i) => (
          <Box key={i} at={b} className={tones.c1.box} delay={0.15 + i * 0.12} />
        ))}
        <Box at={[dog[0] + 0.8, dog[1] + 1.2, dog[2] - 1.6, dog[3] - 2]} className={cn(tones.c2.box, 'border-solid')} delay={0.8} />
        <motion.span
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5 }}
          className={cn('absolute top-[12.5%] left-[56%] rounded px-1.5 py-0.5 text-[11.5px] font-semibold', tones.c1.tag)}
        >
          everything in the foreground
        </motion.span>
        <motion.span
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1 }}
          className={cn('absolute top-[66%] left-[55%] rounded px-1.5 py-0.5 text-[11.5px] font-semibold', tones.c2.tag)}
        >
          the dog
        </motion.span>
      </div>
      <p className="mt-3 px-1 text-[13.5px] leading-relaxed text-body">
        <span className="font-medium text-ink">How the cat stays out of it:</span> to make the room less yellow without touching
        the cat, the temperature pipeline selects everything in the foreground and inverts the selection. Only the room is left.
      </p>
    </div>
  )
}

function ChooseView() {
  return (
    <Panel title={`4 of ${facts.pipelines} pipelines`} aside="the model chooses, code builds">
      <div className="grid gap-2.5 sm:grid-cols-2">
        {changes.map((c, i) => (
          <motion.div
            key={c.pipeline}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.08 + i * 0.1 }}
            className="rounded-2xl border border-line p-3.5"
          >
            <div className="flex items-center gap-2">
              <span className={cn('size-2.5 rounded-full', tones[c.tone].dot)} />
              <code className="font-mono text-[13px] font-medium">{c.pipeline}</code>
            </div>
            <div className="mt-2 text-[12.5px] text-muted">“{c.quote}”</div>
            <div className="mt-1.5 text-[13.5px] leading-snug">{c.built}</div>
          </motion.div>
        ))}
      </div>
      <p className="mt-4 text-[13px] leading-relaxed text-muted">
        The model only says how much, like “much” or “a little”; the pipeline turns that into the setting. A number is used
        only when you wrote it yourself.
      </p>
    </Panel>
  )
}

function BuildView() {
  return (
    <div className="overflow-hidden rounded-[22px] bg-[#111113] shadow-card">
      <div className="flex items-center gap-2 border-b border-white/10 px-4 py-3 text-[12.5px] text-white/60">
        <TerminalSquare className="size-3.5" /> Commands sent to PhotoCraft
        <span className="ml-auto">{commands.length} commands</span>
      </div>
      <ol className="space-y-1 p-4 font-mono text-[12px] leading-relaxed sm:text-[12.5px]">
        {commands.map((c, i) => (
          <motion.li
            key={i}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.05 + i * 0.07 }}
            className="flex min-w-0 gap-2.5"
          >
            <span className={cn('mt-[7px] size-1.5 shrink-0 rounded-full', tones[c.tone].dot)} />
            <span className="min-w-0 break-words">
              <span className="text-white">{c.cmd}</span>
              {c.args && <span className="text-white/50"> {c.args}</span>}
            </span>
          </motion.li>
        ))}
      </ol>
    </div>
  )
}

function ApplyView() {
  return (
    <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_230px]">
      <div className="relative overflow-hidden rounded-[20px] shadow-card" style={{ aspectRatio: '1216 / 684' }}>
        <ReactCompareSlider
          className="h-full w-full"
          handle={
            <ReactCompareSliderHandle
              buttonStyle={{ width: 40, height: 40, border: 0, backdropFilter: 'none', background: '#fff', color: '#111113', boxShadow: '0 6px 20px rgba(0,0,0,.25)' }}
              linesStyle={{ width: 2, background: '#fff', boxShadow: '0 0 8px rgba(0,0,0,.2)' }}
            />
          }
          itemOne={<ReactCompareSliderImage src="media/demo-plan-before.webp" alt="Before the edit" />}
          itemTwo={<ReactCompareSliderImage src="media/demo-plan-after.webp" alt="After the edit" />}
        />
        <span className="pointer-events-none absolute bottom-3 left-3 z-10 rounded-full bg-white/90 px-3 py-1 text-[12.5px] font-medium text-ink">Before</span>
        <span className="pointer-events-none absolute right-3 bottom-3 z-10 rounded-full bg-ink/80 px-3 py-1 text-[12.5px] font-medium text-white">After</span>
      </div>
      <div className="rounded-[20px] border border-line bg-card p-2 shadow-card">
        <div className="flex items-center gap-2 px-2 py-1.5 text-[12.5px] font-semibold">
          <Layers className="size-3.5" /> Layers <span className="ml-auto font-normal text-muted">in the PSD</span>
        </div>
        {layers.map((l, i) => (
          <motion.div
            key={l.name}
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 + i * 0.1 }}
            className={cn('flex items-center gap-2.5 rounded-xl px-2 py-1.5', l.tone && 'bg-tint/70')}
          >
            <Eye className="size-3.5 shrink-0 text-muted" />
            <span className="min-w-0">
              <span className="block text-[12.5px] leading-snug font-medium">{l.name}</span>
              <span className="block text-[11px] text-muted">{l.kind}</span>
            </span>
            {l.tone && <span className={cn('ml-auto size-2 shrink-0 rounded-full', tones[l.tone].dot)} />}
          </motion.div>
        ))}
      </div>
    </div>
  )
}

function CheckView() {
  return (
    <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_260px]">
      <figure>
        <div className="relative overflow-hidden rounded-[20px] shadow-card" style={{ aspectRatio: '1216 / 684' }}>
          <img
            src="media/demo-plan-changed.webp"
            alt="The edited picture with unchanged pixels in grey: the cat, the suitcase and the chair are grey"
            className="h-full w-full object-cover"
          />
        </div>
        <figcaption className="mt-2 px-1 text-[12.5px] text-muted">Coloured: pixels that changed. Grey: pixels that did not.</figcaption>
      </figure>
      <div className="space-y-3">
        <Panel title="Measured" aside={`${checks.length} of ${checks.length}`}>
          <ul className="space-y-2">
            {checks.map((c, i) => (
              <motion.li
                key={c}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.2 + i * 0.35 }}
                className="flex items-start gap-2.5 text-[13px] leading-snug"
              >
                <span className="mt-px grid size-[18px] shrink-0 place-items-center rounded-full bg-ok text-white">
                  <Check className="size-3" strokeWidth={3} />
                </span>
                {c}
              </motion.li>
            ))}
          </ul>
        </Panel>
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 1.3 }}
          className="rounded-[22px] border border-[#bbe5c8] bg-[#f3fbf5] p-4 text-[13px] leading-relaxed text-[#14532d]"
        >
          <span className="font-semibold">Kept: the cat.</span> Every one of its pixels is identical to the original.
        </motion.div>
      </div>
    </div>
  )
}

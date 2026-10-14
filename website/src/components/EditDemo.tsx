import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useInView } from 'motion/react'
import { ReactCompareSlider, ReactCompareSliderHandle, ReactCompareSliderImage } from 'react-compare-slider'
import { Brush, Check, Crop, Eye, Image as ImageIcon, Layers, MessageSquareText, RotateCcw, SunMedium, Type, Wand2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { AppIcon, Em, Intro } from './ui'

type Demo = {
  id: string
  tab: string
  icon: typeof Brush
  request: string
  reply: string
  chips: string[]
  ratio?: string
}

const demos: Demo[] = [
  {
    id: 'dog',
    tab: 'Remove',
    icon: Brush,
    request: 'Remove the dog completely and fill the area with the background that would naturally be behind it. Keep everything else exactly the same.',
    reply: 'Done. Only the area you painted changed; the cat, the case and the light are as they were.',
    chips: ['FLUX.1 Kontext', 'On this PC', '5 min 4 s'],
    ratio: '825 / 557',
  },
  {
    id: 'cactus',
    tab: 'Replace',
    icon: Wand2,
    request: 'Replace the white mug with a small green cactus in a terracotta pot.',
    reply: 'Done. The cactus sits where the mug was, with the same light and the same table.',
    chips: ['FLUX.1 Kontext', 'On this PC', '4 min 28 s'],
    ratio: '624 / 710',
  },
  {
    id: 'polish',
    tab: 'Polish',
    icon: SunMedium,
    request: 'Professional polish',
    reply: 'Done. Two adjustment layers in a PSD, so you can still open it in PhotoCraft and change them.',
    chips: ['PhotoCraft', 'On this PC', '1.8 s'],
    ratio: '1400 / 933',
  },
  {
    id: 'plan',
    tab: 'Plan a retouch',
    icon: Layers,
    request:
      "Make the sunset sky more dramatic, brighten the friends a little, crop to 16:9 and add 'Summer 2026' at the top in a bold white serif with a shadow. Keep their faces natural.",
    reply: 'I understood 4 changes. Nothing runs until you press Apply.',
    chips: ['PhotoCraft studio', 'Plan from a real session'],
  },
]

const plan = [
  { icon: SunMedium, quote: 'Make the sunset sky more dramatic', does: 'Develop: contrast +35, clarity +40, dehaze +16, highlights −40', layer: 'Sky · Develop' },
  { icon: ImageIcon, quote: 'brighten the friends a little', does: 'Find the friends, then brightness on a masked layer', layer: 'The friends · Brightness' },
  { icon: Crop, quote: 'crop to 16:9', does: 'Crop to 1344 × 756', layer: 'Crop 16:9' },
  { icon: Type, quote: "add 'Summer 2026' at the top", does: 'Text · 56.7 pt Georgia, white, top, drop shadow', layer: 'Summer 2026 · Type' },
]

// Where the assistant found each person, as a share of the picture.
const boxes = [
  [9, 13, 17, 87],
  [26, 13, 16, 87],
  [42, 15, 17, 85],
  [59, 13, 16, 87],
  [75, 11, 20, 89],
]

export function EditDemo() {
  const [active, setActive] = useState(0)
  const [run, setRun] = useState(0)
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { once: true, amount: 0.35 })
  const demo = demos[active]

  return (
    <section id="demos" className="scroll-mt-24 px-4 py-24 sm:px-5 sm:py-32">
      <Intro
        badge={
          <>
            <MessageSquareText className="size-3.5 text-accent" /> Edit by asking
          </>
        }
        title={
          <>
            Say what to change. <Em>Keep everything else.</Em>
          </>
        }
        lead="Real requests typed into Image Studio and the pictures that came back, untouched. Drag the line to compare."
      />

      <div ref={ref} className="mx-auto mt-12 max-w-[1180px]">
        <div className="mx-auto flex w-fit max-w-full gap-1 overflow-x-auto rounded-full border border-line bg-card p-1 shadow-card">
          {demos.map((d, i) => (
            <button
              key={d.id}
              type="button"
              onClick={() => {
                setActive(i)
                setRun((r) => r + 1)
              }}
              className={cn(
                'relative flex h-10 shrink-0 items-center gap-2 rounded-full px-4 text-[14px] font-medium transition-colors',
                i === active ? 'text-white' : 'text-body hover:text-ink',
              )}
            >
              {i === active && (
                <motion.span layoutId="demo-pill" className="absolute inset-0 rounded-full bg-ink" transition={{ type: 'spring', stiffness: 420, damping: 36 }} />
              )}
              <d.icon className="relative size-4" />
              <span className="relative">{d.tab}</span>
            </button>
          ))}
        </div>

        <div className="mt-6 grid grid-cols-[minmax(0,1fr)] overflow-hidden rounded-[30px] border border-line bg-card shadow-float lg:grid-cols-[400px_minmax(0,1fr)]">
          <Chat key={`${demo.id}-${run}`} demo={demo} start={inView} onReplay={() => setRun((r) => r + 1)} />
          <div className="relative min-w-0 border-t border-line bg-tint/60 p-3 sm:p-5 lg:border-t-0 lg:border-l">
            <AnimatePresence mode="wait">
              <motion.div
                key={demo.id}
                initial={{ opacity: 0, scale: 0.985 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.985 }}
                transition={{ duration: 0.3 }}
                className="flex h-full items-center justify-center"
              >
                {demo.id === 'plan' ? <PlanStage key={run} start={inView} /> : <Compare demo={demo} />}
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
        <p className="mt-4 text-center text-[13px] text-muted">Times are from a laptop with an RTX 4060 (8 GB).</p>
      </div>
    </section>
  )
}

function Chat({ demo, start, onReplay }: { demo: Demo; start: boolean; onReplay: () => void }) {
  const [stage, setStage] = useState(0) // 0 nothing, 1 request, 2 thinking, 3 reply, 4+ plan steps
  useEffect(() => {
    if (!start) return
    const at = [150, 650, 1500]
    const extra = demo.id === 'plan' ? plan.length + 1 : 0
    const timers = at.map((t, i) => window.setTimeout(() => setStage(i + 1), t))
    for (let i = 0; i < extra; i++) timers.push(window.setTimeout(() => setStage(4 + i), 1900 + i * 520))
    return () => timers.forEach(window.clearTimeout)
  }, [start, demo.id])

  return (
    <div className="flex min-h-[420px] flex-col">
      <div className="flex items-center gap-3 border-b border-line px-5 py-4">
        <AppIcon className="size-8" />
        <div className="leading-tight">
          <div className="text-[14.5px] font-semibold">Image Studio</div>
          <div className="text-[12.5px] text-muted">{demo.chips[0]}</div>
        </div>
        <button
          type="button"
          onClick={onReplay}
          className="ml-auto flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] text-muted transition-colors hover:bg-tint hover:text-ink"
        >
          <RotateCcw className="size-3.5" /> Replay
        </button>
      </div>
      <div className="flex flex-1 flex-col gap-3 p-5">
        <AnimatePresence>
          {stage >= 1 && (
            <motion.div
              initial={{ opacity: 0, y: 10, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              className="ml-auto max-w-[88%] rounded-[20px] rounded-br-md bg-ink px-4 py-3 text-[14.5px] leading-relaxed text-white"
            >
              {demo.request}
            </motion.div>
          )}
          {stage === 2 && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex w-fit gap-1 rounded-[18px] rounded-bl-md bg-tint px-4 py-3.5">
              {[0, 1, 2].map((i) => (
                <motion.span
                  key={i}
                  className="size-1.5 rounded-full bg-muted"
                  animate={{ opacity: [0.3, 1, 0.3] }}
                  transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.15 }}
                />
              ))}
            </motion.div>
          )}
          {stage >= 3 && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="max-w-[92%] rounded-[20px] rounded-bl-md bg-tint px-4 py-3 text-[14.5px] leading-relaxed text-ink"
            >
              {demo.reply}
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {demo.chips.map((c) => (
                  <span key={c} className="rounded-full border border-line bg-card px-2.5 py-0.5 text-[12px] text-body">
                    {c}
                  </span>
                ))}
              </div>
            </motion.div>
          )}
          {demo.id === 'plan' &&
            plan.map(
              (s, i) =>
                stage >= 4 + i && (
                  <motion.div
                    key={s.quote}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    className="flex max-w-[92%] gap-3 rounded-2xl border border-line bg-card px-3.5 py-3"
                  >
                    <span className="grid size-7 shrink-0 place-items-center rounded-full bg-accent-soft text-accent">
                      <s.icon className="size-3.5" />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[13.5px] font-medium">“{s.quote}”</span>
                      <span className="mt-0.5 block text-[12.5px] leading-snug text-muted">{s.does}</span>
                    </span>
                  </motion.div>
                ),
            )}
          {demo.id === 'plan' && stage >= 4 + plan.length && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex items-center gap-2 pl-1 text-[13px] text-body">
              <Check className="size-4 text-ok" /> Kept: their faces natural
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

function Compare({ demo }: { demo: Demo }) {
  return (
    <div className="relative w-full overflow-hidden rounded-[20px] shadow-card" style={{ aspectRatio: demo.ratio, maxWidth: `calc(560px * ${demo.ratio})` }}>
      <ReactCompareSlider
        className="h-full w-full"
        handle={
          <ReactCompareSliderHandle
            buttonStyle={{ width: 44, height: 44, border: 0, backdropFilter: 'none', background: '#fff', color: '#111113', boxShadow: '0 6px 20px rgba(0,0,0,.25)' }}
            linesStyle={{ width: 2, background: '#fff', boxShadow: '0 0 8px rgba(0,0,0,.2)' }}
          />
        }
        itemOne={<ReactCompareSliderImage src={`media/demo-${demo.id}-before.webp`} alt="Before the edit" />}
        itemTwo={<ReactCompareSliderImage src={`media/demo-${demo.id}-after.webp`} alt="After the edit" />}
      />
      <span className="pointer-events-none absolute top-3 left-3 z-10 rounded-full bg-white/90 px-3 py-1 text-[12.5px] font-medium text-ink backdrop-blur">
        Before
      </span>
      <span className="pointer-events-none absolute top-3 right-3 z-10 rounded-full bg-ink/80 px-3 py-1 text-[12.5px] font-medium text-white backdrop-blur">
        After
      </span>
    </div>
  )
}

function PlanStage({ start }: { start: boolean }) {
  const [step, setStep] = useState(0)
  useEffect(() => {
    if (!start) return
    const timers = [1, 2, 3, 4, 5].map((s) => window.setTimeout(() => setStep(s), 1400 + s * 520))
    return () => timers.forEach(window.clearTimeout)
  }, [start])

  return (
    <div className="relative w-full max-w-[760px]">
      <div className="relative overflow-hidden rounded-[20px] shadow-card" style={{ aspectRatio: '1344 / 768' }}>
        <img src="media/demo-plan.webp" alt="Five friends waving on a beach at sunset" className="h-full w-full object-cover" />
        {step >= 2 &&
          boxes.map(([x, y, w, h], i) => (
            <motion.span
              key={i}
              className="absolute rounded-md border-[1.5px] border-dashed border-[#a3e635]"
              style={{ left: `${x}%`, top: `${y}%`, width: `${w}%`, height: `${h}%` }}
              initial={{ opacity: 0, scale: 1.05 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: i * 0.07 }}
            />
          ))}
        {step >= 2 && (
          <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="absolute top-[5%] left-[9%] rounded bg-[#a3e635] px-1.5 py-0.5 text-[11.5px] font-semibold text-[#1a2e05]">
            the friends
          </motion.span>
        )}
      </div>
      {/* The layers the plan will add, one per change */}
      <div className="relative -mt-14 ml-auto mr-3 w-[250px] rounded-2xl border border-line bg-card/95 p-2 shadow-float backdrop-blur sm:-mt-24 sm:mr-[-12px]">
        <div className="flex items-center gap-2 px-2 py-1.5 text-[12.5px] font-semibold">
          <Layers className="size-3.5" /> Layers <span className="ml-auto font-normal text-muted">planned</span>
        </div>
        <div className="flex flex-col-reverse">
          <LayerRow name="Background" kind="Pixel" />
          {plan.map((s, i) => (
            <AnimatePresence key={s.layer}>{step >= i + 1 && <LayerRow name={s.layer} kind="New layer" fresh />}</AnimatePresence>
          ))}
        </div>
      </div>
    </div>
  )
}

function LayerRow({ name, kind, fresh }: { name: string; kind: string; fresh?: boolean }) {
  return (
    <motion.div
      initial={fresh ? { opacity: 0, height: 0 } : false}
      animate={{ opacity: 1, height: 'auto' }}
      className="overflow-hidden"
    >
      <div className={cn('flex items-center gap-2.5 rounded-xl px-2 py-1.5', fresh && 'bg-accent-soft/60')}>
        <Eye className="size-3.5 text-muted" />
        <span className="min-w-0">
          <span className="block truncate text-[12.5px] font-medium">{name}</span>
          <span className="block text-[11px] text-muted">{kind}</span>
        </span>
      </div>
    </motion.div>
  )
}

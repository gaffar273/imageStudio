import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useInView } from 'motion/react'
import { ReactCompareSlider, ReactCompareSliderHandle, ReactCompareSliderImage } from 'react-compare-slider'
import { Brush, MessageSquareText, RotateCcw, SunMedium, Wand2 } from 'lucide-react'
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
                <Compare demo={demo} />
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
  const [stage, setStage] = useState(0) // 0 nothing, 1 request, 2 thinking, 3 reply
  useEffect(() => {
    if (!start) return
    const at = [150, 650, 1500]
    const timers = at.map((t, i) => window.setTimeout(() => setStage(i + 1), t))
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
              key="request"
              initial={{ opacity: 0, y: 10, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              className="ml-auto max-w-[88%] rounded-[20px] rounded-br-md bg-ink px-4 py-3 text-[14.5px] leading-relaxed text-white"
            >
              {demo.request}
            </motion.div>
          )}
          {stage === 2 && (
            <motion.div key="thinking" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex w-fit gap-1 rounded-[18px] rounded-bl-md bg-tint px-4 py-3.5">
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
              key="reply"
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

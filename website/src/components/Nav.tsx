import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowDownToLine, Menu, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { GitHubIcon, Logo } from './ui'
import { links, nav, ORG } from '@/site'

export function Nav({ active }: { active: string }) {
  const [scrolled, setScrolled] = useState(false)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <header className="pointer-events-none fixed inset-x-0 top-0 z-50 flex justify-center px-3 pt-3 sm:pt-4">
      <motion.nav
        layout
        aria-label="Main"
        className={cn(
          'pointer-events-auto flex w-full items-center gap-2 rounded-full border py-1.5 pr-1.5 pl-3 transition-[background,border-color,box-shadow,max-width] duration-500',
          scrolled
            ? 'max-w-[920px] border-line bg-card/80 shadow-float backdrop-blur-xl'
            : 'max-w-[1180px] border-transparent bg-transparent',
        )}
      >
        <a href="#top" aria-label="Image Studio, back to top" className="mr-auto shrink-0">
          <Logo org={ORG.name} />
        </a>
        <div className="hidden items-center lg:flex">
          {nav.map((n) => (
            <a
              key={n.id}
              href={`#${n.id}`}
              className={cn(
                'relative rounded-full px-3 py-2 text-[14px] whitespace-nowrap transition-colors',
                active === n.id ? 'text-ink' : 'text-muted hover:text-ink',
              )}
            >
              {active === n.id && (
                <motion.span layoutId="nav-pill" className="absolute inset-0 rounded-full bg-tint" transition={{ type: 'spring', stiffness: 400, damping: 34 }} />
              )}
              <span className="relative">{n.label}</span>
            </a>
          ))}
        </div>
        <a
          href={links.repo}
          target="_blank"
          rel="noreferrer"
          aria-label="Image Studio on GitHub"
          className="hidden size-10 place-items-center rounded-full text-body transition-colors hover:bg-tint hover:text-ink sm:grid"
        >
          <GitHubIcon className="size-[18px]" />
        </a>
        <a
          href="#download"
          className="hidden h-10 items-center gap-2 rounded-full bg-ink px-4 text-[14px] font-medium text-white transition-colors hover:bg-[#2b2b30] sm:flex whitespace-nowrap"
        >
          <ArrowDownToLine className="size-4" /> Get the app
        </a>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-label={open ? 'Close menu' : 'Open menu'}
          aria-expanded={open}
          className="grid size-10 place-items-center rounded-full bg-card shadow-card lg:hidden"
        >
          {open ? <X className="size-[18px]" /> : <Menu className="size-[18px]" />}
        </button>
      </motion.nav>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.98 }}
            transition={{ duration: 0.2 }}
            className="pointer-events-auto absolute inset-x-3 top-[68px] rounded-3xl border border-line bg-card p-2 shadow-float lg:hidden"
          >
            {nav.map((n) => (
              <a
                key={n.id}
                href={`#${n.id}`}
                onClick={() => setOpen(false)}
                className="block rounded-2xl px-4 py-3 text-[16px] font-medium hover:bg-tint"
              >
                {n.label}
              </a>
            ))}
            <div className="mt-1 grid grid-cols-2 gap-2 p-1">
              <a href={links.repo} className="flex h-11 items-center justify-center gap-2 rounded-full border border-line text-[14px] font-medium">
                <GitHubIcon className="size-4" /> GitHub
              </a>
              <a
                href="#download"
                onClick={() => setOpen(false)}
                className="flex h-11 items-center justify-center gap-2 rounded-full bg-ink text-[14px] font-medium text-white"
              >
                <ArrowDownToLine className="size-4" /> Get the app
              </a>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  )
}

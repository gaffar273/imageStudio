import { nav } from '@/site'

/** Local shortcuts sit below the Image Studio showcase. The site header stays fixed. */
export function Nav() {
  return <nav aria-label="Image Studio sections" className="flex flex-wrap justify-center gap-2 px-4 pb-10">
    {nav.map(item => <a key={item.id} href={'#' + item.id}
      className="rounded-full border border-line bg-card px-4 py-2 text-sm text-body hover:border-line-strong hover:text-ink">{item.label}</a>)}
  </nav>
}

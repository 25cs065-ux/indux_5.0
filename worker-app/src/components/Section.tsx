import type { ReactNode } from 'react'

interface Props {
  index: string
  title: string
  aside?: ReactNode
  children: ReactNode
  className?: string
}

/** Numbered section with a field-notes style label row. */
export default function Section({ index, title, aside, children, className }: Props) {
  const id = `section-${index}`
  return (
    <section className={`section ${className ?? ''}`} aria-labelledby={id}>
      <div className="section-label">
        <span className="section-index">{index}</span>
        <h2 id={id} className="section-title">
          {title}
        </h2>
        {aside && <span className="section-aside">{aside}</span>}
      </div>
      {children}
    </section>
  )
}

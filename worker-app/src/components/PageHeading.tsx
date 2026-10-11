import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'

interface Props {
  index: string
  title: string
  lede?: ReactNode
  /** Move focus here on mount (page changes), for keyboard and screen-reader users. */
  autoFocus?: boolean
}

export default function PageHeading({ index, title, lede, autoFocus }: Props) {
  const ref = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    if (autoFocus) ref.current?.focus({ preventScroll: true })
  }, [autoFocus])

  return (
    <div className="page-heading">
      <p className="page-heading-index mono" aria-hidden="true">
        {index}
      </p>
      <h1 ref={ref} className="page-heading-title" tabIndex={-1}>
        {title}
      </h1>
      {lede && <p className="page-heading-lede">{lede}</p>}
    </div>
  )
}

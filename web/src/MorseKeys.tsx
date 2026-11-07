import { useEffect } from 'react'
import type { MorseDecoder } from './morse.mjs'
import './MorseKeys.css'

type Props = { decoder: MorseDecoder }

export default function MorseKeys({ decoder }: Props) {
  useEffect(() => {
    function handleKey(event: KeyboardEvent) {
      if (event.defaultPrevented || event.isComposing || event.repeat || event.altKey
        || event.ctrlKey || event.metaKey || (event.key !== '.' && event.key !== '-')) return
      const target = event.target
      if (target instanceof HTMLElement && (target.isContentEditable
        || target.closest('input, textarea, select, [role="textbox"]'))) return

      event.preventDefault()
      decoder.symbol(event.key)
    }

    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [decoder])

  return (
    <div className="morse-keys" role="group" aria-label="Manual Morse keys">
      <div className="morse-keys-symbols">
        <button type="button" onClick={() => decoder.symbol('.')} aria-keyshortcuts=".">
          <span className="morse-key-mark" aria-hidden="true">·</span>
          <span>Dot</span>
          <kbd aria-hidden="true">.</kbd>
        </button>
        <button type="button" onClick={() => decoder.symbol('-')} aria-keyshortcuts="-">
          <span className="morse-key-mark" aria-hidden="true">−</span>
          <span>Dash</span>
          <kbd aria-hidden="true">-</kbd>
        </button>
      </div>
      <div className="morse-keys-boundaries">
        <button type="button" onClick={decoder.commitLetter}>End letter</button>
        <button type="button" onClick={decoder.commitWord}>End word</button>
      </div>
      <p>Use the keys or type <span>.</span> and <span>−</span>. Pauses separate letters and words.</p>
    </div>
  )
}

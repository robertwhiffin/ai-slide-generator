import { useEffect, useRef } from 'react';

/** Elements whose own Escape handling wins: typing fields. */
const TEXT_FIELD = 'input, textarea, select, [contenteditable]';
/** Inline Escape handlers (page header, session history, element tree, feedback drawer) own Escape here. */
const ESCAPE_OWNER = '[data-escape-owner]';

/**
 * Escape stops the running generation, the same as the stop button.
 *
 * One bubble-phase window listener per `active` change, with `onStop` read from a ref: a listener
 * re-registered on every render would run after ConfirmDialog's and could reopen its dialog. Escape is
 * left alone when something else already handled it (`defaultPrevented`), when any dialog is open, and
 * when it is pressed in a text field or inside an element that owns Escape.
 */
export function useEscapeToStop(active: boolean, onStop: () => void): void {
  const onStopRef = useRef(onStop);
  onStopRef.current = onStop;

  useEffect(() => {
    if (!active) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      if (document.querySelector('[role="dialog"]')) return;
      const target = e.target instanceof Element ? e.target : null;
      if (target?.closest(TEXT_FIELD) || target?.closest(ESCAPE_OWNER)) return;
      onStopRef.current();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [active]);
}

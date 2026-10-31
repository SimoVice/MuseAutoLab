import { useEffect, useRef, useState } from 'react';
import type { ReactNode, RefObject } from 'react';
import type { Component } from './types';
import './presentation-stage.css';

type Props = {
  viewerRef: RefObject<HTMLDivElement | null>;
  compact: boolean;
  title: string;
  sourceNote: string;
  components: Component[];
  selectedPart?: Component;
  onSelect: (id: string | null) => void;
  children: ReactNode;
};

export default function PresentationStage({ viewerRef, compact, title, sourceNote, components, selectedPart, onSelect, children }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [reservedHeight, setReservedHeight] = useState(0);
  const stage = useRef<HTMLDivElement | null>(null);
  const toggle = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!expanded || !stage.current) return;
    const element = stage.current;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    // Keep the mounted scene in place while making the surrounding workspace inert.
    const surroundings: { element: HTMLElement; inert: boolean }[] = [];
    let branch: HTMLElement = element;
    while (branch.parentElement) {
      for (const sibling of branch.parentElement.children) {
        if (sibling !== branch && sibling instanceof HTMLElement) {
          surroundings.push({ element: sibling, inert: sibling.inert });
          sibling.inert = true;
        }
      }
      branch = branch.parentElement;
      if (branch.classList.contains('app-shell')) break;
    }
    toggle.current?.focus({ preventScroll: true });

    const focusableElements = () => Array.from(element.querySelectorAll<HTMLElement>(
      'button:not(:disabled), select:not(:disabled), input:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])',
    )).filter((candidate) => candidate.getClientRects().length > 0 && !candidate.closest('[inert]'));
    function handleKey(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        setExpanded(false);
      }
      if (event.key !== 'Tab') return;
      const controls = focusableElements();
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && (document.activeElement === first || !element.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !element.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
      }
    }
    function keepFocus(event: FocusEvent) {
      if (event.target instanceof Node && !element.contains(event.target)) toggle.current?.focus({ preventScroll: true });
    }
    document.addEventListener('keydown', handleKey);
    document.addEventListener('focusin', keepFocus);
    return () => {
      document.removeEventListener('keydown', handleKey);
      document.removeEventListener('focusin', keepFocus);
      document.body.style.overflow = previousOverflow;
      for (const sibling of surroundings) sibling.element.inert = sibling.inert;
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, [expanded]);

  function toggleExpanded() {
    if (!expanded) setReservedHeight(stage.current?.getBoundingClientRect().height ?? 0);
    setExpanded((current) => !current);
  }

  return <>
    {expanded && <div className="presentation-stage-space" style={{ height: reservedHeight }} aria-hidden="true" />}
    <div ref={(element) => { stage.current = element; viewerRef.current = element; }}
      className={`viewer-shell presentation-stage${compact ? ' viewer-compact' : ''}${expanded ? ' presentation-stage-expanded' : ''}`}
      role={expanded ? 'dialog' : 'region'} aria-modal={expanded || undefined}
      aria-labelledby="presentation-stage-title" aria-describedby="presentation-stage-source">
      <div className="viewer-topline stage-topline">
        <strong id="presentation-stage-title">{title}</strong>
        <button ref={toggle} className="stage-expand-button" type="button" onClick={toggleExpanded}
          aria-expanded={expanded} aria-controls="presentation-stage-model">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {expanded ? <path d="M4 9h5V4m11 5h-5V4M4 15h5v5m11-5h-5v5" /> : <path d="M9 4H4v5m11-5h5v5M4 15v5h5m6 0h5v-5" />}
          </svg>
          <span>{expanded ? 'Exit expanded view' : 'Expand 3D view'}</span>
        </button>
      </div>
      <div id="presentation-stage-model" className="stage-model-content">{children}</div>
      <div className="stage-selection">
        <label htmlFor="stage-component">Component
          <select id="stage-component" aria-label="Component in expanded view" value={selectedPart?.id ?? ''}
            onChange={(event) => onSelect(event.target.value || null)}>
            <option value="">Full model</option>
            {components.map((part) => <option key={part.id} value={part.id}>{part.label}</option>)}
          </select>
        </label>
        <div className="stage-component-detail" aria-live="polite">
          <strong>{selectedPart?.label ?? 'Explore the complete design'}</strong>
          <span>{selectedPart ? `${selectedPart.size.map((value) => new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(value)).join(' × ')} mm · model envelope` : 'Select a component in the model or menu to inspect it.'}</span>
        </div>
      </div>
      <p id="presentation-stage-source" className="stage-source-note">{sourceNote} <span>Physical fit unverified.</span></p>
    </div>
  </>;
}

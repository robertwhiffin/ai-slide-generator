import React from 'react';
import { Info } from 'lucide-react';
import type { DeckMode } from '../../services/api';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/ui/tooltip';

interface DeckModeSelectProps {
  value: DeckMode;
  locked: boolean;
  onChange: (mode: DeckMode) => void;
}

/**
 * The deck's engine choice, shown on the right of ChatInput's hint line. The native select is
 * controlled (always a defined value) and disabled once the mode is fixed; the info trigger stays
 * enabled so the explanation can still be read. It is a type="button" because it sits in a <form>.
 */
export const DeckModeSelect: React.FC<DeckModeSelectProps> = ({ value, locked, onChange }) => (
  <TooltipProvider delayDuration={0}>
    <span className="inline-flex items-center gap-1.5">
      <span className="text-xs font-medium text-gray-500">Mode</span>
      <select
        aria-label="Mode"
        data-testid="deck-mode-select"
        value={value}
        disabled={locked}
        onChange={(e) => onChange(e.target.value as DeckMode)}
        className="px-1.5 py-0.5 border border-gray-300 rounded text-xs bg-white text-foreground focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
      >
        <option value="agent">Agent mode</option>
        <option value="legacy">Legacy mode</option>
      </select>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label="About modes"
            className="inline-flex items-center rounded text-muted-foreground hover:text-foreground focus:outline-none focus-visible:ring-1 focus-visible:ring-blue-500"
          >
            <Info className="h-3.5 w-3.5" data-testid="deck-mode-info" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs space-y-1.5 text-xs">
          <p>Agent mode: plans the deck, then builds it slide by slide, showing progress as it goes.</p>
          <p>Legacy mode: a less capable agent. Usually faster, but harder to converse with and to adapt to changes.</p>
          <p>You can change this until you send your first message. After that it's fixed for this deck.</p>
        </TooltipContent>
      </Tooltip>
    </span>
  </TooltipProvider>
);

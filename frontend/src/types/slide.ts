import type { VerificationResult } from './verification';
import type { SlideFinding } from './finding';

export interface Slide {
  index: number;
  slide_id: string;
  html: string;
  scripts: string;  // JavaScript for this slide's charts (e.g., Chart.js initialization)
  verification?: VerificationResult;  // LLM as Judge verification result (merged from verification_map)
  content_hash?: string;  // Hash of slide content for verification lookup
  created_by?: string;
  created_at?: string;   // ISO 8601 timestamp
  modified_by?: string;
  modified_at?: string;  // ISO 8601 timestamp
}

// ---------------------------------------------------------------------------
// DeckSpec — the TypeScript mirror of src/domain/deck_spec.py
// ---------------------------------------------------------------------------
//
// There is no runtime bridge between these declarations and the Pydantic models
// they mirror, which is exactly why Finding and SlideFinding drifted once
// already.  The guard is frontend/src/services/__tests__/deckSpecConformance.test.ts,
// which reads src/domain/deck_spec.py as text and compares field names in both
// directions.  Add a field to either side and the other side must follow.
//
// Field names stay snake_case here, unlike SlideFinding: the read path projects
// Finding onto camelCase (_finding_to_camel in session_manager.py) but serves the
// deck spec as the parsed JSON object verbatim, so the wire shape IS the Python
// shape.  Do not "tidy" these into camelCase.

/**
 * Which brand to use — identifiers ONLY, never compiled style content (L3).
 *
 * A snapshot of compiled CSS in the spec would go stale against
 * COMPILER_VERSION, so the spec stores ids and the content is resolved on
 * demand from them.  A surface rendering this must therefore show *which* brand,
 * not what it compiles to.
 *
 * Invariants enforced server-side: design_system_id and slide_style_id are
 * mutually exclusive (L1); template_id requires design_system_id (L3).
 */
export interface DesignContractRef {
  design_system_id?: number | null;
  template_id?: number | null;
  slide_style_id?: number | null;
}

export interface ResolvedFigure {
  key: string;
  value: string;
  source: string;
}

export interface ResolvedData {
  synthesis: string;
  figures: ResolvedFigure[];
  gaps: string[];
}

/**
 * Specification for a single slide.
 *
 * `position` — not the list index — is the canonical identity of the slide
 * within the deck; the two diverge after a delete or a partial rebuild.
 * `template_section_index` is an index into the template's section list, never
 * markup (M3).
 */
export interface SlideSpec {
  position: number;
  purpose: string;
  content_brief: string;
  assumes: string;
  hands_off: string;
  data_references: string[];
  template_section_index?: number | null;
}

/**
 * The architect's plan for the deck, committed once and read back verbatim by
 * every downstream node.
 *
 * Review criteria are deliberately NOT a field (§4.2): if the architect authored
 * the standard its own output is judged against, review independence would be
 * nominal.
 */
export interface DeckSpec {
  title: string;
  audience: string;
  purpose: string;
  argument: string;
  call_to_action: string;
  narrative_arc: string[];
  design_contract: DesignContractRef;
  resolved_data: ResolvedData;
  slides: SlideSpec[];
}

export interface SlideDeck {
  title: string;
  slide_count: number;
  css: string;
  external_scripts: string[];
  scripts: string;
  slides: Slide[];
  html_content?: string;
  created_by?: string;
  created_at?: string;
  modified_by?: string;
  modified_at?: string;
  version?: number;  // Server-side optimistic lock version from SessionSlideDeck
  /**
   * One FLAT deck-level list of review findings, each carrying its own
   * slideIndex — not a per-slide index.  get_slide_deck emits it on all three
   * of its read paths, so it is never undefined on a deck read from the API;
   * optional only because decks constructed client-side do not carry it.
   */
  findings?: SlideFinding[];
  /**
   * The architect's plan for this deck, or null when it has none.
   *
   * `get_slide_deck` emits this key on all three of its dict-returning read
   * paths (`_read_deck_spec` in session_manager.py), unconditionally, so a deck
   * read from the API never leaves it `undefined`:
   *   - a deck with a spec        -> the parsed spec OBJECT (not a JSON string)
   *   - a specless deck, or one whose deck_spec_json will not parse -> `null`
   * `undefined` therefore means only "this deck was constructed client-side".
   * Consumers must handle both absent and null; SpecView renders its empty state
   * for either.
   */
  deck_spec?: DeckSpec | null;
}

export interface SlideContext {
  indices: number[];
  slide_htmls: string[];
}

export interface ReplacementInfo {
  start_index?: number;
  original_count?: number;
  replacement_count?: number;
  net_change?: number;
  operation?: string;
  original_indices?: number[];
  success?: boolean;
  error?: string | null;
  canvas_ids?: string[];
  is_add_operation?: boolean;
  /** RC11: Conflict note when selection differs from text reference */
  conflict_note?: string;
  /** RC14: Deck sync error when frontend/backend state mismatch */
  sync_error?: string;
}

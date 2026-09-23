import {
  ASSEMBLY_CONDITIONS,
  type AgentKey,
  type AssemblyCondition,
  type AssemblyRulesV2,
  type ContentIdentity,
  type CustomAnchor,
  type CustomTextBlock,
  type ProtectedStageView,
} from '../../../api/agentDefinitions';

const ANCHOR_LABELS: Record<CustomAnchor, string> = {
  after_authored_prompt: 'After authored prompt',
  after_deck_brief: 'After deck-brief re-review',
  after_environment_constraints: 'After environment constraints',
};

const CONDITION_LABELS: Record<AssemblyCondition, string> = {
  always: 'Always',
  design_system_active: 'Design System active',
  design_system_inactive: 'Design System inactive',
  payload_has_deck_brief: 'Payload has a deck brief',
};

interface AssemblyEditorProps {
  agentKey: AgentKey;
  /** The locked, server-derived protected view. The client never reconstructs it. */
  protectedStageView: ProtectedStageView[];
  /** Immutable local v2 rules, or `null` while the role is still on v1. */
  rules: AssemblyRulesV2 | null;
  protectedAssembly: ContentIdentity;
  disabled: boolean;
  onAddBlock(anchor: CustomAnchor): void;
  onChangeText(blockId: string, text: string): void;
  onChangeCondition(blockId: string, condition: AssemblyCondition): void;
  onDeleteBlock(blockId: string): void;
  onMoveBlock(blockId: string, direction: 'up' | 'down'): void;
}

function ProtectedStageRow({ row }: { row: ProtectedStageView }) {
  return (
    <div
      role="group"
      aria-label={`Protected stage: ${row.label}`}
      data-stage-id={row.stage_id}
      className="rounded-md border border-gray-300 bg-white p-3"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        {/*
          The row's accessible name already comes from the group's aria-label. Server-owned
          stage labels such as "Graph Version 1 runtime payload" would otherwise collide
          with the workbench's own "Graph Version 1" heading in any name-substring query,
          so the visible title is deliberately not a heading.
        */}
        <p className="text-sm font-semibold text-gray-900">{row.label}</p>
        <span className="rounded-full bg-gray-200 px-2 py-0.5 text-xs font-medium text-gray-700">
          Locked
        </span>
      </div>
      <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-2 text-xs text-gray-600">
        <dt>Condition</dt>
        <dd>{CONDITION_LABELS[row.condition]}</dd>
        <dt>Protected version</dt>
        <dd>{row.bundle_version}</dd>
        <dt>Protected digest</dt>
        <dd className="break-all font-mono">{row.bundle_digest}</dd>
      </dl>
      <pre className="mt-2 whitespace-pre-wrap break-words font-mono text-xs text-gray-800">
        {row.display_text}
      </pre>
    </div>
  );
}

function CustomBlockRow({
  agentKey,
  block,
  anchor,
  position,
  siblingCount,
  disabled,
  onChangeText,
  onChangeCondition,
  onDeleteBlock,
  onMoveBlock,
}: {
  agentKey: AgentKey;
  block: CustomTextBlock;
  anchor: CustomAnchor;
  position: number;
  siblingCount: number;
  disabled: boolean;
  onChangeText(blockId: string, text: string): void;
  onChangeCondition(blockId: string, condition: AssemblyCondition): void;
  onDeleteBlock(blockId: string): void;
  onMoveBlock(blockId: string, direction: 'up' | 'down'): void;
}) {
  const textId = `${agentKey}-custom-${block.block_id}-text`;
  const conditionId = `${agentKey}-custom-${block.block_id}-condition`;
  return (
    <div
      role="group"
      aria-label={`Custom block ${position + 1} at ${ANCHOR_LABELS[anchor]}`}
      data-block-id={block.block_id}
      className="rounded-md border border-blue-200 bg-blue-50 p-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-semibold text-blue-900">Custom text</span>
        <div className="flex gap-1">
          {position > 0 && (
            <button type="button" disabled={disabled} onClick={() => onMoveBlock(block.block_id, 'up')}>
              Move up
            </button>
          )}
          {position < siblingCount - 1 && (
            <button type="button" disabled={disabled} onClick={() => onMoveBlock(block.block_id, 'down')}>
              Move down
            </button>
          )}
          <button type="button" disabled={disabled} onClick={() => onDeleteBlock(block.block_id)}>
            Delete
          </button>
        </div>
      </div>
      <label htmlFor={textId} className="mt-2 block text-xs font-medium text-blue-900">
        Block text
      </label>
      <textarea
        id={textId}
        value={block.text}
        disabled={disabled}
        onChange={(event) => onChangeText(block.block_id, event.currentTarget.value)}
        className="mt-1 min-h-20 w-full rounded-md border border-blue-300 p-2 font-mono text-sm"
      />
      <label htmlFor={conditionId} className="mt-2 block text-xs font-medium text-blue-900">
        Condition
      </label>
      <select
        id={conditionId}
        value={block.condition}
        disabled={disabled}
        onChange={(event) => onChangeCondition(
          block.block_id,
          event.currentTarget.value as AssemblyCondition,
        )}
        className="mt-1 block rounded-md border border-blue-300 p-1 text-sm"
      >
        {ASSEMBLY_CONDITIONS.map((condition) => (
          <option key={condition} value={condition}>{CONDITION_LABELS[condition]}</option>
        ))}
      </select>
    </div>
  );
}

/**
 * Renders the locked server-derived protected rows and, for a v2 definition only,
 * the editable custom siblings at each legal pre-payload anchor. It never fetches,
 * never writes, and never reconstructs protected text.
 */
export function AssemblyEditor({
  agentKey,
  protectedStageView,
  rules,
  protectedAssembly,
  disabled,
  onAddBlock,
  onChangeText,
  onChangeCondition,
  onDeleteBlock,
  onMoveBlock,
}: AssemblyEditorProps) {
  // Anchor legality is read from the server view, never invented by the client.
  // An anchor group is placed after the last protected row that declares it, so a
  // custom sibling can never land after the payload or terminal stages.
  const anchorPlacement = new Map<CustomAnchor, number>();
  protectedStageView.forEach((row, index) => {
    for (const anchor of row.legal_adjacent_custom_anchors) anchorPlacement.set(anchor, index);
  });
  const legalAnchors: CustomAnchor[] = [
    'after_authored_prompt',
    ...[...anchorPlacement.keys()],
  ];

  const editable = rules !== null;
  const blocksAt = (anchor: CustomAnchor): CustomTextBlock[] => (
    rules === null ? [] : rules.custom_blocks.filter((block) => block.anchor === anchor)
  );

  const anchorGroup = (anchor: CustomAnchor) => {
    if (!editable) return null;
    const siblings = blocksAt(anchor);
    return (
      <div
        key={`anchor-${anchor}`}
        role="group"
        aria-label={`Custom blocks: ${ANCHOR_LABELS[anchor]}`}
        className="space-y-2 rounded-md border border-dashed border-blue-300 p-2"
      >
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-blue-800">
            {ANCHOR_LABELS[anchor]}
          </span>
          <button type="button" disabled={disabled} onClick={() => onAddBlock(anchor)}>
            {`Add custom block ${ANCHOR_LABELS[anchor]}`}
          </button>
        </div>
        {siblings.map((block, position) => (
          <CustomBlockRow
            key={block.block_id}
            agentKey={agentKey}
            block={block}
            anchor={anchor}
            position={position}
            siblingCount={siblings.length}
            disabled={disabled}
            onChangeText={onChangeText}
            onChangeCondition={onChangeCondition}
            onDeleteBlock={onDeleteBlock}
            onMoveBlock={onMoveBlock}
          />
        ))}
      </div>
    );
  };

  const anchorsAfter = (index: number) => legalAnchors.filter(
    (anchor) => (anchor === 'after_authored_prompt' ? -1 : anchorPlacement.get(anchor)) === index,
  );

  return (
    <section aria-label="Assembly pipeline" className="space-y-3">
      <div role="group" aria-label="Protected assembly identity" className="text-xs text-gray-600">
        <p>
          {`Protected assembly version ${protectedAssembly.version}`}
        </p>
        <p className="break-all font-mono">{protectedAssembly.digest}</p>
        {!editable && (
          <p className="mt-2 text-gray-700">
            Custom text blocks require the Graph Version 2 protected assembly.
          </p>
        )}
      </div>

      <div role="group" aria-label="Authored prompt stage" className="rounded-md border border-gray-200 bg-white p-3">
        <h5 className="text-sm font-semibold text-gray-900">Authored prompt</h5>
        <p className="mt-1 text-xs text-gray-600">Edited on the Prompt tab.</p>
      </div>
      {anchorsAfter(-1).map(anchorGroup)}

      {protectedStageView.map((row, index) => (
        <div key={row.stage_id} className="space-y-3">
          <ProtectedStageRow row={row} />
          {anchorsAfter(index).map(anchorGroup)}
        </div>
      ))}
    </section>
  );
}

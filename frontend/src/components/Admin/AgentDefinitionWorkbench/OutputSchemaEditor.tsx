/**
 * Output Schema Editor — displays the server-owned field descriptor metadata
 * as read-only protected labels, and exposes description/examples guidance
 * editing plus the `diagnostic_notes` optional-field picker (v2 contracts only).
 */
import type { AgentKey, FieldDescriptor } from '../../../api/agentDefinitions';
import {
  schemaOverlayFormFromDefinition,
  type DraftEditorEntry,
  type EditableSchemaOverlayForm,
} from './draftEditorState';

interface OutputSchemaEditorProps {
  agentKey: AgentKey;
  entry: DraftEditorEntry;
  disabled: boolean;
  onToggleOptionalField(fieldName: string): void;
  onEditFieldDescription(fieldName: string, description: string): void;
  onEditFieldExamples(fieldName: string, examples: string): void;
  onUpgradeSchemaContract(): void;
}

/**
 * Returns the effective overlay form: the user's local edits when present, or
 * the saved definition's overlay when the user has not yet made any changes.
 */
function effectiveOverlay(entry: DraftEditorEntry): EditableSchemaOverlayForm {
  return entry.local.schema_overlay ?? schemaOverlayFormFromDefinition(entry.saved);
}

interface ProtectedLabelProps {
  name: string;
  value: string;
}

function ProtectedLabel({ name, value }: ProtectedLabelProps) {
  return (
    <div className="flex gap-2 text-xs text-gray-500">
      <span className="font-medium">{name}:</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}

interface OptionalFieldRowProps {
  descriptor: FieldDescriptor;
  isSelected: boolean;
  guidanceDescription: string;
  guidanceExamples: string;
  disabled: boolean;
  onToggle(): void;
  onDescriptionChange(value: string): void;
  onExamplesChange(value: string): void;
}

function OptionalFieldRow({
  descriptor,
  isSelected,
  guidanceDescription,
  guidanceExamples,
  disabled,
  onToggle,
  onDescriptionChange,
  onExamplesChange,
}: OptionalFieldRowProps) {
  const checkboxId = `optional-field-${descriptor.name}`;
  const descId = `optional-field-desc-${descriptor.name}`;
  const examplesId = `optional-field-examples-${descriptor.name}`;

  return (
    <div
      role="group"
      aria-label={`Optional field: ${descriptor.name}`}
      className="rounded-md border border-gray-200 bg-white p-3 space-y-2"
    >
      {/* Protected field name and selector */}
      <div className="flex items-center gap-2">
        <input
          id={checkboxId}
          type="checkbox"
          aria-label={`Select ${descriptor.name}`}
          checked={isSelected}
          disabled={disabled}
          onChange={onToggle}
          className="h-4 w-4 rounded border-gray-300 text-blue-600"
        />
        <label htmlFor={checkboxId} className="text-sm font-semibold text-gray-900 font-mono">
          {descriptor.name}
        </label>
      </div>

      {/* Protected schema metadata — read-only labels, never inputs */}
      <div className="ml-6 space-y-1">
        <ProtectedLabel name="type" value={descriptor.schema.type.join(' | ')} />
        <ProtectedLabel name="default" value={String(descriptor.schema.default)} />
        <ProtectedLabel name="max_items" value={String(descriptor.schema.max_items)} />
      </div>

      {/* Server-owned descriptor text */}
      <div className="ml-6 text-xs text-gray-600">{descriptor.description}</div>

      {/* Editable guidance overrides */}
      <div className="ml-6 space-y-2">
        <div>
          <label htmlFor={descId} className="block text-xs font-medium text-gray-700">
            Description override
          </label>
          <textarea
            id={descId}
            aria-label="Description override"
            value={guidanceDescription}
            disabled={disabled}
            onChange={(event) => onDescriptionChange(event.currentTarget.value)}
            rows={2}
            className="mt-1 w-full rounded-md border border-gray-300 p-2 text-sm font-normal disabled:bg-gray-50"
          />
        </div>
        <div>
          <label htmlFor={examplesId} className="block text-xs font-medium text-gray-700">
            Examples override (JSON array)
          </label>
          <textarea
            id={examplesId}
            aria-label="Examples override (JSON array)"
            value={guidanceExamples}
            disabled={disabled}
            onChange={(event) => onExamplesChange(event.currentTarget.value)}
            rows={2}
            placeholder='["example value"]'
            className="mt-1 w-full rounded-md border border-gray-300 p-2 font-mono text-xs disabled:bg-gray-50"
          />
        </div>
      </div>
    </div>
  );
}

export function OutputSchemaEditor({
  agentKey,
  entry,
  disabled,
  onToggleOptionalField,
  onEditFieldDescription,
  onEditFieldExamples,
  onUpgradeSchemaContract,
}: OutputSchemaEditorProps) {
  const overlay = effectiveOverlay(entry);
  const selectableFields = entry.saved.selectable_optional_fields;
  const isV2Schema = entry.saved.schema_contract.version >= 2;

  return (
    <div className="space-y-4">
      {/* Schema contract summary */}
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs text-gray-500">
          Schema contract version {entry.saved.schema_contract.version}
        </span>
        {!isV2Schema && (
          <button
            type="button"
            aria-label="Schema Upgrade"
            disabled={disabled}
            onClick={onUpgradeSchemaContract}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            Schema Upgrade
          </button>
        )}
      </div>

      {/* Selectable optional fields (v2 only) */}
      {isV2Schema && selectableFields.length > 0 && (
        <div className="space-y-3">
          <h4 className="text-sm font-semibold text-gray-800">Optional output fields</h4>
          {selectableFields.map((descriptor) => {
            const guidance = overlay.field_overrides[descriptor.name];
            return (
              <OptionalFieldRow
                key={descriptor.name}
                descriptor={descriptor}
                isSelected={overlay.additional_optional_fields.includes(descriptor.name)}
                guidanceDescription={guidance?.description ?? ''}
                guidanceExamples={guidance?.examples ?? ''}
                disabled={disabled}
                onToggle={() => onToggleOptionalField(descriptor.name)}
                onDescriptionChange={(value) => onEditFieldDescription(descriptor.name, value)}
                onExamplesChange={(value) => onEditFieldExamples(descriptor.name, value)}
              />
            );
          })}
        </div>
      )}

      {/* Existing field overrides (for fields already in schema_overlay.field_overrides) */}
      {Object.entries(overlay.field_overrides)
        // Only show entries for canonical fields (not selectable optional fields — those
        // are shown above). If there are no canonical overrides, this section is empty.
        .filter(([key]) => !selectableFields.some((d) => d.name === key))
        .map(([fieldName, guidance]) => (
          <div
            key={fieldName}
            role="group"
            aria-label={`Field override: ${fieldName}`}
            className="rounded-md border border-gray-200 bg-white p-3 space-y-2"
          >
            <p className="text-sm font-semibold text-gray-900 font-mono">{fieldName}</p>
            <div className="space-y-2">
              <div>
                <label
                  htmlFor={`${agentKey}-override-desc-${fieldName}`}
                  className="block text-xs font-medium text-gray-700"
                >
                  Description override
                </label>
                <textarea
                  id={`${agentKey}-override-desc-${fieldName}`}
                  aria-label="Description override"
                  value={guidance.description}
                  disabled={disabled}
                  onChange={(event) => onEditFieldDescription(fieldName, event.currentTarget.value)}
                  rows={2}
                  className="mt-1 w-full rounded-md border border-gray-300 p-2 text-sm font-normal disabled:bg-gray-50"
                />
              </div>
              <div>
                <label
                  htmlFor={`${agentKey}-override-examples-${fieldName}`}
                  className="block text-xs font-medium text-gray-700"
                >
                  Examples override (JSON array)
                </label>
                <textarea
                  id={`${agentKey}-override-examples-${fieldName}`}
                  aria-label="Examples override (JSON array)"
                  value={guidance.examples}
                  disabled={disabled}
                  onChange={(event) => onEditFieldExamples(fieldName, event.currentTarget.value)}
                  rows={2}
                  placeholder='["example value"]'
                  className="mt-1 w-full rounded-md border border-gray-300 p-2 font-mono text-xs disabled:bg-gray-50"
                />
              </div>
            </div>
          </div>
        ))}

      {/* v1: no selectable optional fields, show a note */}
      {!isV2Schema && (
        <p className="text-xs text-gray-500">
          Schema Upgrade enables optional output fields for this role.
        </p>
      )}
    </div>
  );
}

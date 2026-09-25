/**
 * Output Schema Editor — displays the server-owned canonical-field and optional-field
 * descriptor metadata as read-only protected labels, and exposes only description/examples
 * guidance editing plus the `diagnostic_notes` optional-field picker (v2 contracts only).
 */
import type {
  AgentKey,
  CanonicalFieldDescriptor,
  FieldDescriptor,
} from '../../../api/agentDefinitions';
import {
  overlayExamplesError,
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

function ExamplesError({ id, message }: { id: string; message: string | null }) {
  return message ? (
    <span id={id} role="alert" className="mt-1 block text-xs text-red-700">{message}</span>
  ) : null;
}

interface CanonicalFieldRowProps {
  agentKey: AgentKey;
  field: CanonicalFieldDescriptor;
  guidanceDescription: string;
  guidanceExamples: string;
  disabled: boolean;
  onDescriptionChange(value: string): void;
  onExamplesChange(value: string): void;
}

/**
 * One code-owned canonical output field. Name, type, required, default and enum are
 * server-derived text in a description list — never inputs. The two guidance textareas
 * carry field-specific accessible names so no name is a substring of another's.
 */
function CanonicalFieldRow({
  agentKey,
  field,
  guidanceDescription,
  guidanceExamples,
  disabled,
  onDescriptionChange,
  onExamplesChange,
}: CanonicalFieldRowProps) {
  const descId = `${agentKey}-canonical-desc-${field.name}`;
  const examplesId = `${agentKey}-canonical-examples-${field.name}`;
  const examplesErrorId = `${examplesId}-error`;
  const examplesError = overlayExamplesError(guidanceExamples);
  const properties: Array<[string, string]> = [
    ['name', field.name],
    ['type', field.type],
    ['required', field.required ? 'yes' : 'no'],
  ];
  if (!field.required) properties.push(['default', JSON.stringify(field.default)]);
  if (field.enum !== null) properties.push(['enum', field.enum.join(', ')]);

  return (
    <div
      role="group"
      aria-label={`Canonical field: ${field.name}`}
      className="rounded-md border border-gray-200 bg-white p-3 space-y-2"
    >
      <p className="text-sm font-semibold text-gray-900 font-mono">{field.name}</p>
      <div role="group" aria-label={`Protected properties of ${field.name}`}>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-2 text-xs text-gray-500">
          {properties.map(([term, value]) => (
            <div key={term} className="contents">
              <dt className="font-medium">{term}</dt>
              <dd className="font-mono break-words">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="space-y-2">
        <div>
          <label htmlFor={descId} className="block text-xs font-medium text-gray-700">
            Description guidance
          </label>
          <textarea
            id={descId}
            aria-label={`Description guidance for ${field.name}`}
            value={guidanceDescription}
            disabled={disabled}
            onChange={(event) => onDescriptionChange(event.currentTarget.value)}
            rows={2}
            className="mt-1 w-full rounded-md border border-gray-300 p-2 text-sm font-normal disabled:bg-gray-50"
          />
        </div>
        <div>
          <label htmlFor={examplesId} className="block text-xs font-medium text-gray-700">
            Examples guidance (JSON array)
          </label>
          <textarea
            id={examplesId}
            aria-label={`Examples guidance for ${field.name} (JSON array)`}
            aria-invalid={examplesError !== null}
            aria-describedby={examplesError !== null ? examplesErrorId : undefined}
            value={guidanceExamples}
            disabled={disabled}
            onChange={(event) => onExamplesChange(event.currentTarget.value)}
            rows={2}
            placeholder='["example value"]'
            className="mt-1 w-full rounded-md border border-gray-300 p-2 font-mono text-xs disabled:bg-gray-50"
          />
          <ExamplesError id={examplesErrorId} message={examplesError} />
        </div>
      </div>
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
  const examplesErrorId = `${examplesId}-error`;
  const examplesError = overlayExamplesError(guidanceExamples);

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
            aria-invalid={examplesError !== null}
            aria-describedby={examplesError !== null ? examplesErrorId : undefined}
            value={guidanceExamples}
            disabled={disabled}
            onChange={(event) => onExamplesChange(event.currentTarget.value)}
            rows={2}
            placeholder='["example value"]'
            className="mt-1 w-full rounded-md border border-gray-300 p-2 font-mono text-xs disabled:bg-gray-50"
          />
          <ExamplesError id={examplesErrorId} message={examplesError} />
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
  const canonicalFields = entry.saved.canonical_fields;
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

      {/* Code-owned canonical fields: protected labels plus editable guidance */}
      {canonicalFields.length > 0 && (
        <section
          role="region"
          aria-labelledby={`${agentKey}-canonical-fields-heading`}
          className="space-y-3"
        >
          <h4 id={`${agentKey}-canonical-fields-heading`} className="text-sm font-semibold text-gray-800">
            Canonical output fields
          </h4>
          <p className="text-xs text-gray-500">
            Name, type, required, default and enum are code-owned and cannot be changed here.
            Only description and examples guidance is editable.
          </p>
          {canonicalFields.map((field) => {
            const guidance = overlay.field_overrides[field.name];
            return (
              <CanonicalFieldRow
                key={field.name}
                agentKey={agentKey}
                field={field}
                guidanceDescription={guidance?.description ?? ''}
                guidanceExamples={guidance?.examples ?? ''}
                disabled={disabled}
                onDescriptionChange={(value) => onEditFieldDescription(field.name, value)}
                onExamplesChange={(value) => onEditFieldExamples(field.name, value)}
              />
            );
          })}
        </section>
      )}

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

      {/* Any other saved override (a name that is neither canonical nor selectable) stays
          visible so no stored guidance is hidden; the server rejects it on the next Save. */}
      {Object.entries(overlay.field_overrides)
        .filter(([key]) => !selectableFields.some((d) => d.name === key)
          && !canonicalFields.some((field) => field.name === key))
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
                  aria-invalid={overlayExamplesError(guidance.examples) !== null}
                  value={guidance.examples}
                  disabled={disabled}
                  onChange={(event) => onEditFieldExamples(fieldName, event.currentTarget.value)}
                  rows={2}
                  placeholder='["example value"]'
                  className="mt-1 w-full rounded-md border border-gray-300 p-2 font-mono text-xs disabled:bg-gray-50"
                />
                <ExamplesError
                  id={`${agentKey}-override-examples-${fieldName}-error`}
                  message={overlayExamplesError(guidance.examples)}
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

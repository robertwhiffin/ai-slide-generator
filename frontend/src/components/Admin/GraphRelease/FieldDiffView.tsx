import type { JsonValue, ReleaseDiffField } from '../../../api/agentDefinitions';
import { lineDiff } from './lineDiff';
import { jsonText } from './releaseText';

const LINE_PREFIX = { same: '  ', removed: '- ', added: '+ ' } as const;
const LINE_CLASS = {
  same: 'text-gray-700',
  removed: 'bg-red-50 text-red-800',
  added: 'bg-green-50 text-green-800',
} as const;

/**
 * One field's `before → after` diff, as text only: `prompt_text` line by line through
 * `lineDiff`, every other field as JSON. Shared by the Definition Diff tab (#269) and
 * the Release History comparison (#270).
 */
export function FieldDiffView({
  field,
  before,
  after,
  testIdPrefix = 'release-diff',
}: {
  field: ReleaseDiffField;
  before: JsonValue;
  after: JsonValue;
  testIdPrefix?: string;
}) {
  if (field === 'prompt_text' && typeof before === 'string' && typeof after === 'string') {
    return (
      <ul aria-label={field} className="overflow-x-auto rounded border border-gray-200 font-mono text-xs">
        {lineDiff(before, after).map((line, index) => (
          <li key={index} data-kind={line.kind} className={`whitespace-pre ${LINE_CLASS[line.kind]}`}>
            {`${LINE_PREFIX[line.kind]}${line.text}`}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <pre
      data-testid={`${testIdPrefix}-${field}`}
      className="overflow-x-auto rounded border border-gray-200 bg-gray-50 p-2 font-mono text-xs"
    >
      {`${jsonText(before)} → ${jsonText(after)}`}
    </pre>
  );
}

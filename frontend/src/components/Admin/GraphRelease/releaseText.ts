import { parseInstant, type JsonValue } from '../../../api/agentDefinitions';

/** A JSON value as indented text (never markup). */
export function jsonText(value: JsonValue): string {
  return JSON.stringify(value, null, 2);
}

/**
 * An ISO instant in fixed UTC copy. A zoneless value is UTC (`parseInstant`), so a
 * SQLite `…Z` and a naive `/workbench` spelling of one instant read the same.
 */
export function formatInstant(value: string): string {
  const instant = parseInstant(value);
  if (instant === null) return value;
  return `${new Date(instant).toISOString().slice(0, 19).replace('T', ' ')} UTC`;
}

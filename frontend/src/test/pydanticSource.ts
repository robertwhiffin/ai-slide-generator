/**
 * Shared reader of Pydantic model source text: used by the DeckSpec conformance
 * test and the Markdown field-coverage guards.
 */

/**
 * Field names declared on a Pydantic model, in declaration order.
 *
 * Docstrings are stripped first rather than skipped line by line: this codebase's
 * docstrings are long prose and several of their lines would otherwise parse as
 * annotated assignments.
 */
export function pythonClassBody(source: string, className: string): string {
  const stripped = source.replace(/"""[\s\S]*?"""/g, '');
  const header = new RegExp(`^class ${className}\\(BaseModel\\):$`, 'm').exec(stripped);
  if (!header) {
    throw new Error(
      `class ${className}(BaseModel) not found in the Python source. Either it was `
      + 'renamed (update this mirror and slide.ts) or the base class changed.',
    );
  }
  const afterHeader = stripped.slice(header.index + header[0].length);
  const nextClass = afterHeader.search(/^class \w+/m);
  return nextClass === -1 ? afterHeader : afterHeader.slice(0, nextClass);
}

export function pythonModelFields(source: string, className: string): string[] {
  const body = pythonClassBody(source, className);

  const fields: string[] = [];
  for (const line of body.split('\n')) {
    // Exactly four spaces of indent: model fields sit at class-body level, while
    // method bodies sit at eight and decorators start with '@'.
    const match = /^ {4}([a-z_][A-Za-z0-9_]*)\s*:\s*\S/.exec(line);
    if (match) fields.push(match[1]);
  }
  return fields;
}

/** Field name -> annotation text ('Optional[int]', 'list[SlideSpec]', …), in declaration order. */
export function pythonModelFieldAnnotations(source: string, className: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const line of pythonClassBody(source, className).split('\n')) {
    // Same 4-space class-body rule as pythonModelFields; a default (`= None`) is not part of the annotation.
    const match = /^ {4}([a-z_][A-Za-z0-9_]*)\s*:\s*([^=]+?)\s*(?:=.*)?$/.exec(line);
    if (match) out.set(match[1], match[2].trim());
  }
  return out;
}

/** Every `class X(BaseModel):` in the source, in declaration order (docstrings stripped first). */
export function pythonModelClasses(source: string): string[] {
  const stripped = source.replace(/"""[\s\S]*?"""/g, '');
  return [...stripped.matchAll(/^class (\w+)\(BaseModel\):$/gm)].map((m) => m[1]);
}

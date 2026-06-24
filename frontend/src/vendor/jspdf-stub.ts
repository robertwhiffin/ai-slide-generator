/**
 * Build-time stub when jspdf cannot be installed from the corporate npm proxy.
 * PDF export is disabled; the rest of the app (including deck sharing) works normally.
 */
export default class jsPDF {
  internal = {
    pageSize: {
      getWidth: () => 297,
      getHeight: () => 210,
    },
  };

  constructor(_opts?: unknown) {}

  addPage(): void {}

  addImage(..._args: unknown[]): void {}

  save(_filename: string): void {
    throw new Error('PDF export is unavailable in this build environment.');
  }
}

/**
 * Ambient declarations for browser-side dynamic imports inside page.evaluate().
 *
 * Paths like '/src/components/...' are resolved by the Vite dev server, not by
 * Node/TypeScript.  Without this declaration, tsc would emit TS2307 ("Cannot find
 * module '/src/...'") for every such import.
 */
declare module '/src/*';

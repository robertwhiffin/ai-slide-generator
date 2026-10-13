import '@testing-library/jest-dom';

// jsdom stubs for browser APIs used by SlideViewer subcomponents.

// ThumbnailRibbon calls scrollRef.current?.scrollIntoView() to keep the
// current thumbnail visible.  jsdom does not implement this method.
Element.prototype.scrollIntoView = vi.fn();

// SlideStage uses ResizeObserver to track the stage container's dimensions.
// jsdom does not provide ResizeObserver.
global.ResizeObserver = class ResizeObserver {
  observe() { /* no-op */ }
  unobserve() { /* no-op */ }
  disconnect() { /* no-op */ }
};

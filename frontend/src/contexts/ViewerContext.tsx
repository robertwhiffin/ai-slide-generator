import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

/** Single member today; speaker notes add 'notes' later without restructuring (spec §5). */
export type DrawerTab = 'feedback';

const VIEW_STATE_KEY = 'tellr-viewer-view-state';
const DEFAULT_HEIGHT = 180;
const MIN_HEIGHT = 96;
const MAX_HEIGHT = 480;

interface PersistedViewState {
  drawerOpen: boolean;
  drawerHeight: number;
  activeTab: DrawerTab;
}

const DEFAULT_VIEW_STATE: PersistedViewState = {
  drawerOpen: true,
  drawerHeight: DEFAULT_HEIGHT,
  activeTab: 'feedback',
};

function readViewState(): PersistedViewState {
  try {
    const raw = localStorage.getItem(VIEW_STATE_KEY);
    if (!raw) return DEFAULT_VIEW_STATE;
    return { ...DEFAULT_VIEW_STATE, ...(JSON.parse(raw) as Partial<PersistedViewState>) };
  } catch {
    return DEFAULT_VIEW_STATE;
  }
}

function writeViewState(state: PersistedViewState): void {
  try {
    localStorage.setItem(VIEW_STATE_KEY, JSON.stringify(state));
  } catch {
    // Non-fatal: view state is a convenience.
  }
}

interface ViewerContextValue {
  currentIndex: number;
  setCurrentIndex: (i: number) => void;
  next: () => void;
  prev: () => void;
  first: () => void;
  last: () => void;
  drawerOpen: boolean;
  setDrawerOpen: (v: boolean) => void;
  drawerHeight: number;
  setDrawerHeight: (px: number) => void;
  activeTab: DrawerTab;
  setActiveTab: (t: DrawerTab) => void;
}

const ViewerContext = createContext<ViewerContextValue | null>(null);

export const ViewerProvider: React.FC<{ slideCount: number; children: React.ReactNode }> = ({
  slideCount,
  children,
}) => {
  const initial = readViewState();
  const [currentIndex, setIndex] = useState(0);
  const [drawerOpen, setOpen] = useState(initial.drawerOpen);
  const [drawerHeight, setHeight] = useState(initial.drawerHeight);
  const [activeTab, setTab] = useState<DrawerTab>(initial.activeTab);

  useEffect(() => {
    writeViewState({ drawerOpen, drawerHeight, activeTab });
  }, [drawerOpen, drawerHeight, activeTab]);

  // Keep the index addressable when the deck shrinks (delete/reorder).
  useEffect(() => {
    if (slideCount === 0) {
      setIndex(0);
    } else if (currentIndex > slideCount - 1) {
      setIndex(slideCount - 1);
    }
  }, [slideCount, currentIndex]);

  const clamp = useCallback(
    (i: number) => Math.min(Math.max(i, 0), Math.max(slideCount - 1, 0)),
    [slideCount],
  );

  const setCurrentIndex = useCallback((i: number) => setIndex(clamp(i)), [clamp]);

  const value = useMemo<ViewerContextValue>(
    () => ({
      currentIndex,
      setCurrentIndex,
      next: () => setIndex(i => clamp(i + 1)),
      prev: () => setIndex(i => clamp(i - 1)),
      first: () => setIndex(0),
      last: () => setIndex(clamp(slideCount - 1)),
      drawerOpen,
      setDrawerOpen: setOpen,
      drawerHeight,
      setDrawerHeight: (px: number) => setHeight(Math.min(Math.max(px, MIN_HEIGHT), MAX_HEIGHT)),
      activeTab,
      setActiveTab: setTab,
    }),
    [currentIndex, setCurrentIndex, clamp, slideCount, drawerOpen, drawerHeight, activeTab],
  );

  return <ViewerContext.Provider value={value}>{children}</ViewerContext.Provider>;
};

export function useViewer(): ViewerContextValue {
  const ctx = useContext(ViewerContext);
  if (!ctx) throw new Error('useViewer must be used within a ViewerProvider');
  return ctx;
}

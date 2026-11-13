import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { useTour } from './TourContext';
import { RELEASES } from '../whatsNew/releases';
import {
  WHATS_NEW_STORAGE_KEY,
  compareVersions,
  isReleaseVersion,
  newestVersion,
  sortNewestFirst,
  unseenVersions,
  type ReleaseNotes,
} from '../whatsNew/releaseNotes';

interface WhatsNewContextValue {
  isOpen: boolean;
  /** Newest first, only releases with items. */
  releases: ReleaseNotes[];
  /** Versions with items newer than the last one dismissed. */
  unseen: Set<string>;
  hasNotes: boolean;
  open: () => void;
  /** Records the newest release (empty ones included) as seen, then closes. */
  close: () => void;
}

const WhatsNewContext = createContext<WhatsNewContextValue | null>(null);

export function WhatsNewProvider({
  children,
  releases: allReleases = RELEASES,
  autoOpenDelayMs = 800,
}: {
  children: React.ReactNode;
  releases?: ReleaseNotes[];
  autoOpenDelayMs?: number;
}) {
  const { hasCompletedTour, isTourActive, showWelcome } = useTour();
  const [isOpen, setIsOpen] = useState(false);
  const [lastSeen, setLastSeen] = useState<string | null>(() => localStorage.getItem(WHATS_NEW_STORAGE_KEY));

  // Live tour values for the one-shot timer, and the mount-time values for the one-shot decision.
  const tourRef = useRef({ isTourActive, showWelcome });
  tourRef.current = { isTourActive, showWelcome };
  const mountRef = useRef({ hasCompletedTour, lastSeen, allReleases, autoOpenDelayMs });

  // The pending auto-open timer, so a manual open() or a close() can cancel it.
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelAutoOpen = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const record = useCallback((all: ReleaseNotes[]) => {
    const newest = newestVersion(all);
    if (newest === null) return;
    // Never lower the stored version: after a rollback the bundle can be older than it.
    const stored = localStorage.getItem(WHATS_NEW_STORAGE_KEY);
    const target =
      stored !== null && isReleaseVersion(stored) && compareVersions(stored, newest) > 0 ? stored : newest;
    setLastSeen(target);
    localStorage.setItem(WHATS_NEW_STORAGE_KEY, target);
  }, []);

  // Auto-open is decided once, at mount.
  useEffect(() => {
    const m = mountRef.current;
    if (!m.hasCompletedTour) return;
    if (unseenVersions(m.allReleases, m.lastSeen).size === 0) return;
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      const { isTourActive: active, showWelcome: welcome } = tourRef.current;
      if (!active && !welcome) setIsOpen(true);
    }, m.autoOpenDelayMs);
    return cancelAutoOpen;
  }, [cancelAutoOpen]);

  // A brand-new user finishing the welcome guide or tour has seen everything; never open for it.
  const prevCompleted = useRef(hasCompletedTour);
  useEffect(() => {
    if (!prevCompleted.current && hasCompletedTour) record(allReleases);
    prevCompleted.current = hasCompletedTour;
  }, [hasCompletedTour, allReleases, record]);

  const releases = useMemo(
    () => sortNewestFirst(allReleases).filter((r) => r.items.length > 0),
    [allReleases],
  );
  const unseen = useMemo(() => unseenVersions(allReleases, lastSeen), [allReleases, lastSeen]);

  const open = useCallback(() => {
    // Never stack on the welcome guide or the tour.
    const { isTourActive: active, showWelcome: welcome } = tourRef.current;
    if (active || welcome) return;
    cancelAutoOpen();
    setIsOpen(true);
  }, [cancelAutoOpen]);
  const close = useCallback(() => {
    cancelAutoOpen();
    record(allReleases);
    setIsOpen(false);
  }, [allReleases, record, cancelAutoOpen]);

  return (
    <WhatsNewContext.Provider value={{ isOpen, releases, unseen, hasNotes: releases.length > 0, open, close }}>
      {children}
    </WhatsNewContext.Provider>
  );
}

export function useWhatsNew() {
  const ctx = useContext(WhatsNewContext);
  if (!ctx) throw new Error('useWhatsNew must be used within WhatsNewProvider');
  return ctx;
}

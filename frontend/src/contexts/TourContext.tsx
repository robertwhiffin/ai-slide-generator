import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';

const TOUR_STORAGE_KEY = 'tellr-app-tour-completed';

interface TourContextValue {
  isTourActive: boolean;
  showWelcome: boolean;
  hasCompletedTour: boolean;
  startTour: () => void;
  dismissWelcome: () => void;
  endTour: () => void;
  resetTour: () => void;
}

const TourContext = createContext<TourContextValue | null>(null);

export function TourProvider({ children }: { children: React.ReactNode }) {
  const [isTourActive, setIsTourActive] = useState(false);
  const [showWelcome, setShowWelcome] = useState(false);
  const [hasCompletedTour, setHasCompletedTour] = useState(() => {
    return localStorage.getItem(TOUR_STORAGE_KEY) === 'true';
  });

  useEffect(() => {
    if (!hasCompletedTour) {
      const timer = setTimeout(() => setShowWelcome(true), 800);
      return () => clearTimeout(timer);
    }
  }, [hasCompletedTour]);

  const startTour = useCallback(() => {
    setShowWelcome(false);
    setIsTourActive(true);
  }, []);

  const dismissWelcome = useCallback(() => {
    setShowWelcome(false);
    setHasCompletedTour(true);
    localStorage.setItem(TOUR_STORAGE_KEY, 'true');
  }, []);

  const endTour = useCallback(() => {
    setIsTourActive(false);
    setHasCompletedTour(true);
    localStorage.setItem(TOUR_STORAGE_KEY, 'true');
  }, []);

  const resetTour = useCallback(() => {
    setHasCompletedTour(false);
    localStorage.removeItem(TOUR_STORAGE_KEY);
  }, []);

  return (
    <TourContext.Provider value={{ isTourActive, showWelcome, hasCompletedTour, startTour, dismissWelcome, endTour, resetTour }}>
      {children}
    </TourContext.Provider>
  );
}

export function useTour() {
  const ctx = useContext(TourContext);
  if (!ctx) throw new Error('useTour must be used within TourProvider');
  return ctx;
}

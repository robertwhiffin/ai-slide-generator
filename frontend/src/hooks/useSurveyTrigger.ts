/**
 * Hook to trigger the satisfaction survey popup.
 *
 * Logic:
 * - After a successful generation, checks localStorage for cooldown (7 days)
 * - If eligible, starts a 30-second timer
 * - If another generation starts during the timer, resets it
 * - After 30s idle, triggers the survey
 * - Writes timestamp to localStorage immediately (dismiss or complete both count)
 */
import { useState, useEffect, useRef, useCallback } from 'react';

const STORAGE_KEY = 'tellr_survey_last_shown';
const COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000; // 7 days
const DELAY_MS = 30 * 1000; // 30 seconds

export const useSurveyTrigger = () => {
  const [showSurvey, setShowSurvey] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const isEligible = useCallback((): boolean => {
    const lastShown = localStorage.getItem(STORAGE_KEY);
    if (!lastShown) return true;
    const elapsed = Date.now() - parseInt(lastShown, 10);
    return elapsed >= COOLDOWN_MS;
  }, []);

  const markShown = useCallback(() => {
    localStorage.setItem(STORAGE_KEY, Date.now().toString());
  }, []);

  const onGenerationComplete = useCallback(() => {
    if (!isEligible()) return;
    clearTimer();
    timerRef.current = setTimeout(() => {
      markShown();
      setShowSurvey(true);
    }, DELAY_MS);
  }, [isEligible, clearTimer, markShown]);

  const onGenerationStart = useCallback(() => {
    clearTimer();
  }, [clearTimer]);

  const closeSurvey = useCallback(() => {
    setShowSurvey(false);
  }, []);

  useEffect(() => {
    return () => clearTimer();
  }, [clearTimer]);

  return { showSurvey, closeSurvey, onGenerationComplete, onGenerationStart };
};

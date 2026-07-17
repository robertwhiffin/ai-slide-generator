import { useCallback } from 'react';
import { api } from '../services/api';

/**
 * Shared hook for the Google OAuth popup flow.
 *
 * Opens a popup for Google consent, listens for a postMessage callback,
 * and falls back to polling the popup's closed state + auth status check.
 *
 * @returns `openOAuthPopup()` — resolves `true` if authorized, `false` otherwise.
 */
export function useGoogleOAuthPopup() {
  const openOAuthPopup = useCallback(async (): Promise<boolean> => {
    const { url } = await api.getGoogleSlidesAuthUrl();

    return new Promise<boolean>((resolve) => {
      const popup = window.open(url, 'google-slides-auth', 'width=600,height=700,popup=yes');

      const handleMessage = (event: MessageEvent) => {
        // SDR-4437 MEDIUM-3: the callback page posts with an explicit
        // targetOrigin; only trust messages from our own origin so a hostile
        // page cannot spoof a "connected" state.
        if (event.origin !== window.location.origin) return;
        if (event.data?.type === 'google-slides-auth') {
          cleanup();
          resolve(event.data.success === true);
        }
      };

      const pollTimer = setInterval(() => {
        if (popup?.closed) {
          cleanup();
          api.checkGoogleSlidesAuth().then(({ authorized }) => resolve(authorized));
        }
      }, 1000);

      const cleanup = () => {
        clearInterval(pollTimer);
        window.removeEventListener('message', handleMessage);
      };

      window.addEventListener('message', handleMessage);
    });
  }, []);

  return { openOAuthPopup };
}

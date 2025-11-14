import { useEffect } from 'react';
import { useSelection } from '../contexts/SelectionContext';

export const useKeyboardShortcuts = (): void => {
  const { clearSelection, hasSelection } = useSelection();

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && hasSelection) {
        clearSelection();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [clearSelection, hasSelection]);
};


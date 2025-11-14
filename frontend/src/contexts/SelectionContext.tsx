import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from 'react';
import type { Slide } from '../types/slide';

interface SelectionContextValue {
  selectedIndices: number[];
  selectedSlides: Slide[];
  hasSelection: boolean;
  setSelection: (indices: number[], slides: Slide[]) => void;
  clearSelection: () => void;
}

const SelectionContext = createContext<SelectionContextValue | undefined>(
  undefined,
);

export const SelectionProvider: React.FC<React.PropsWithChildren> = ({
  children,
}) => {
  const [selectedIndices, setSelectedIndices] = useState<number[]>([]);
  const [selectedSlides, setSelectedSlides] = useState<Slide[]>([]);

  const setSelection = useCallback((indices: number[], slides: Slide[]) => {
    const zipped = indices
      .map((idx, position) => ({
        idx,
        slide: slides[position],
      }))
      .filter(
        (
          item,
        ): item is {
          idx: number;
          slide: Slide;
        } => typeof item.idx === 'number' && Boolean(item.slide),
      )
      .sort((a, b) => a.idx - b.idx);

    setSelectedIndices(zipped.map(item => item.idx));
    setSelectedSlides(zipped.map(item => item.slide));
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedIndices([]);
    setSelectedSlides([]);
  }, []);

  const value = useMemo<SelectionContextValue>(
    () => ({
      selectedIndices,
      selectedSlides,
      hasSelection: selectedIndices.length > 0,
      setSelection,
      clearSelection,
    }),
    [selectedIndices, selectedSlides, setSelection, clearSelection],
  );

  return (
    <SelectionContext.Provider value={value}>
      {children}
    </SelectionContext.Provider>
  );
};

export const useSelection = (): SelectionContextValue => {
  const context = useContext(SelectionContext);
  if (!context) {
    throw new Error('useSelection must be used within a SelectionProvider');
  }
  return context;
};


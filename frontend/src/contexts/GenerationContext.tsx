import React, { createContext, useCallback, useContext, useState } from 'react';

interface GenerationContextType {
  /** Whether slide generation is currently in progress */
  isGenerating: boolean;
  /** Set the generation state */
  setIsGenerating: (value: boolean) => void;
  /** Increment when a generation completes so history panel can refetch */
  historyInvalidationKey: number;
  /** Call after a generation completes to refresh the history list */
  invalidateHistory: () => void;
}

const GenerationContext = createContext<GenerationContextType | undefined>(undefined);

export const GenerationProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [isGenerating, setIsGenerating] = useState(false);
  const [historyInvalidationKey, setHistoryInvalidationKey] = useState(0);
  const invalidateHistory = useCallback(() => {
    setHistoryInvalidationKey((k) => k + 1);
  }, []);

  return (
    <GenerationContext.Provider
      value={{
        isGenerating,
        setIsGenerating,
        historyInvalidationKey,
        invalidateHistory,
      }}
    >
      {children}
    </GenerationContext.Provider>
  );
};

export const useGeneration = (): GenerationContextType => {
  const context = useContext(GenerationContext);
  if (context === undefined) {
    throw new Error('useGeneration must be used within a GenerationProvider');
  }
  return context;
};


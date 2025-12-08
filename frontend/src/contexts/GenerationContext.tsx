import React, { createContext, useContext, useState } from 'react';

interface GenerationContextType {
  /** Whether slide generation is currently in progress */
  isGenerating: boolean;
  /** Set the generation state */
  setIsGenerating: (value: boolean) => void;
}

const GenerationContext = createContext<GenerationContextType | undefined>(undefined);

export const GenerationProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [isGenerating, setIsGenerating] = useState(false);

  return (
    <GenerationContext.Provider
      value={{
        isGenerating,
        setIsGenerating,
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


import React from 'react';

interface TooltipProps {
  text: string;
  children: React.ReactNode;
  position?: 'top' | 'bottom' | 'left' | 'right';
  align?: 'center' | 'start' | 'end';
}

export const Tooltip: React.FC<TooltipProps> = ({
  text,
  children,
  position = 'bottom',
  align = 'center',
}) => {
  const getPositionClasses = () => {
    if (position === 'top' || position === 'bottom') {
      const vertical = position === 'top' ? 'bottom-full mb-1' : 'top-full mt-1';
      const horizontal = {
        center: 'left-1/2 -translate-x-1/2',
        start: 'left-0',
        end: 'right-0',
      }[align];
      return `${vertical} ${horizontal}`;
    }
    // left/right positions
    const horizontal = position === 'left' ? 'right-full mr-1' : 'left-full ml-1';
    return `${horizontal} top-1/2 -translate-y-1/2`;
  };

  return (
    <div className="group/tooltip relative inline-flex">
      {children}
      <span
        className={`
          pointer-events-none absolute z-[9999] whitespace-nowrap
          rounded bg-gray-900 px-2 py-1 text-xs text-white shadow-lg
          opacity-0 transition-opacity group-hover/tooltip:opacity-100
          ${getPositionClasses()}
        `}
      >
        {text}
      </span>
    </div>
  );
};


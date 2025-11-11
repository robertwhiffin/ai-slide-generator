import React, { useMemo } from 'react';
import { Slide, SlideDeck } from '../../types/slide';

interface SlideTileProps {
  slide: Slide;
  slideDeck: SlideDeck;
  index: number;
}

export const SlideTile: React.FC<SlideTileProps> = ({ slide, slideDeck, index }) => {
  // Build complete HTML for iframe
  const slideHTML = useMemo(() => {
    return `
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  ${slideDeck.external_scripts.map(src => 
    `<script src="${src}"></script>`
  ).join('\n  ')}
  <style>${slideDeck.css}</style>
</head>
<body>
  ${slide.html}
  <script>${slideDeck.scripts}</script>
</body>
</html>
    `.trim();
  }, [slide.html, slideDeck.css, slideDeck.scripts, slideDeck.external_scripts]);

  return (
    <div className="bg-white rounded-lg shadow-md overflow-hidden">
      {/* Slide Header */}
      <div className="px-4 py-2 bg-gray-100 border-b flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">
          Slide {index + 1}
        </span>
        {/* Phase 2: Add edit/delete buttons here */}
      </div>

      {/* Slide Preview */}
      <div className="relative bg-gray-200" style={{ paddingBottom: '56.25%' }}>
        <iframe
          srcDoc={slideHTML}
          title={`Slide ${index + 1}`}
          className="absolute top-0 left-0 w-full h-full border-0"
          sandbox="allow-scripts"
          style={{
            transform: 'scale(1)',
            transformOrigin: 'top left',
          }}
        />
      </div>
    </div>
  );
};


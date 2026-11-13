import { useEffect, useRef } from 'react';
import { X, Sparkles } from 'lucide-react';
import { useWhatsNew } from '@/contexts/WhatsNewContext';
import { formatReleaseMonth } from '@/whatsNew/releaseNotes';

export function WhatsNewModal() {
  const { isOpen, releases, unseen, close } = useWhatsNew();
  const gotItRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (isOpen) gotItRef.current?.focus();
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        // Mark it handled so useEscapeToStop does not also stop a running generation.
        e.preventDefault();
        close();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [isOpen, close]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[10001] flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="What's new in Tellr"
        className="w-full max-w-xl mx-4 rounded-2xl bg-white shadow-2xl overflow-hidden"
      >
        <div className="flex items-center justify-between px-6 py-5 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-blue-600 text-white">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-gray-900">What's new in Tellr</h2>
              <p className="text-sm text-gray-500">Highlights from each release</p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={close}
            className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="max-h-[60vh] overflow-y-auto px-6 py-5">
          {releases.map((release, index) => {
            const isNew = unseen.has(release.version);
            return (
              <section
                key={release.version}
                aria-label={`Tellr ${release.version}`}
                className={index > 0 ? 'mt-5 pt-5 border-t border-gray-100' : ''}
              >
                <div className="flex items-center gap-2 mb-2">
                  <h3 className={`text-base font-semibold ${isNew ? 'text-gray-900' : 'text-gray-600'}`}>
                    {release.version}
                  </h3>
                  {isNew && (
                    <span className="px-2 py-0.5 text-xs font-medium text-blue-700 bg-blue-50 rounded-full">
                      New
                    </span>
                  )}
                  <span className="text-xs text-gray-400">{formatReleaseMonth(release.date)}</span>
                </div>
                <ul
                  className={`list-disc pl-5 space-y-1.5 text-sm leading-relaxed ${
                    isNew ? 'text-gray-700' : 'text-gray-500'
                  }`}
                >
                  {release.items.map((item) => (
                    <li key={item.title}>
                      <strong>{item.title}.</strong> {item.body}
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>

        <div className="flex items-center justify-end px-6 py-4 border-t border-gray-100 bg-gray-50/50">
          <button
            ref={gotItRef}
            type="button"
            onClick={close}
            className="px-5 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  );
}

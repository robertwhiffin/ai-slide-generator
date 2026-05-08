import React, { createContext, useContext, useState, useCallback } from 'react';

type ToastType = 'success' | 'error' | 'info';

interface ToastLink {
  text: string;
  url: string;
}

interface ToastOptions {
  /** Render a clickable link after the message text. Auto-makes the toast persistent. */
  link?: ToastLink;
  /** Disable the 5-second auto-dismiss; user must click to clear. Implicitly true when `link` is set. */
  persistent?: boolean;
}

interface Toast {
  id: number;
  message: string;
  type: ToastType;
  link?: ToastLink;
}

interface ToastContextType {
  showToast: (message: string, type?: ToastType, options?: ToastOptions) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

let nextId = 0;

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const showToast = useCallback(
    (message: string, type: ToastType = 'info', options?: ToastOptions) => {
      const id = nextId++;
      setToasts(prev => [...prev, { id, message, type, link: options?.link }]);
      // Persist when a link is present (user needs time to click) or when the
      // caller explicitly requested it. Otherwise auto-dismiss after 5s.
      const persistent = options?.persistent || !!options?.link;
      if (!persistent) {
        setTimeout(() => {
          setToasts(prev => prev.filter(t => t.id !== id));
        }, 5000);
      }
    },
    [],
  );

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {toasts.length > 0 && (
        <div className="fixed bottom-20 right-4 z-50 flex flex-col gap-2" data-testid="toast-container">
          {toasts.map(toast => (
            <div
              key={toast.id}
              data-testid="toast"
              className={`px-4 py-3 rounded-lg shadow-lg text-white text-sm max-w-sm flex items-center gap-3 ${
                toast.type === 'error' ? 'bg-red-600' :
                toast.type === 'success' ? 'bg-green-600' :
                'bg-gray-800'
              }`}
            >
              <span className="flex-1">{toast.message}</span>
              {toast.link && (
                <a
                  href={toast.link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline font-semibold whitespace-nowrap"
                  onClick={(e) => e.stopPropagation()}
                >
                  {toast.link.text} →
                </a>
              )}
              <button
                type="button"
                aria-label="Dismiss"
                className="opacity-70 hover:opacity-100"
                onClick={() => setToasts(prev => prev.filter(t => t.id !== toast.id))}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
    </ToastContext.Provider>
  );
};

export const useToast = (): ToastContextType => {
  const context = useContext(ToastContext);
  if (context === undefined) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
};

import { Layers, Compass, ArrowRight } from 'lucide-react';
import { useTour } from '../../contexts/TourContext';

export function WelcomeModal() {
  const { showWelcome, startTour, dismissWelcome } = useTour();

  if (!showWelcome) return null;

  return (
    <div className="fixed inset-0 z-[10001] flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="w-full max-w-md mx-4 rounded-2xl bg-white shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-300">
        {/* Header gradient */}
        <div className="bg-gradient-to-br from-blue-600 to-indigo-700 px-8 pt-10 pb-8 text-center">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-white/20 backdrop-blur mb-5">
            <Layers className="w-8 h-8 text-white" />
          </div>
          <h2 className="text-2xl font-bold text-white mb-2">Welcome to Tellr</h2>
          <p className="text-blue-100 text-sm leading-relaxed">
            AI-powered slide generation — describe your ideas and get polished presentations in seconds.
          </p>
        </div>

        {/* Body */}
        <div className="px-8 py-6">
          <p className="text-gray-600 text-sm leading-relaxed mb-6">
            Tellr lets you create, edit, and share slide decks through a conversational AI interface. 
            Configure tools, styles, and prompts to match your workflow — then just describe what you need.
          </p>

          <div className="space-y-3">
            <button
              onClick={startTour}
              className="w-full flex items-center justify-center gap-2 px-5 py-3 bg-blue-600 text-white rounded-xl font-medium hover:bg-blue-700 transition-colors"
            >
              <Compass className="w-4 h-4" />
              Take the App Tour
            </button>
            <button
              onClick={dismissWelcome}
              className="w-full flex items-center justify-center gap-2 px-5 py-3 text-gray-600 rounded-xl font-medium hover:bg-gray-100 transition-colors"
            >
              Skip and Get Started
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

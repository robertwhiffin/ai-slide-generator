/**
 * Intercom-style feedback chat popover.
 *
 * Anchored above the feedback button in the bottom-right.
 * Contains a mini chat interface for AI-powered feedback collection.
 */
import React, { useState, useRef, useEffect } from 'react';
import { FiX, FiSend } from 'react-icons/fi';
import { api } from '../../services/api';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

interface FeedbackPopoverProps {
  onClose: () => void;
}

const GREETING = "What's on your mind? Tell me about your experience with tellr.";

export const FeedbackPopover: React.FC<FeedbackPopoverProps> = ({ onClose }) => {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: GREETING },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [summaryReady, setSummaryReady] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Refocus input after loading completes
  useEffect(() => {
    if (!loading && !submitted) {
      inputRef.current?.focus();
    }
  }, [loading, submitted]);

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed || loading) return;

    const userMessage: Message = { role: 'user', content: trimmed };
    const newMessages = [...messages, userMessage];
    setMessages(newMessages);
    setInput('');
    setLoading(true);

    try {
      // Build conversation history for API (exclude initial greeting)
      const conversationHistory = newMessages
        .slice(1)  // skip greeting
        .map(({ role, content }) => ({ role, content }));

      const response = await api.feedbackChat(conversationHistory);

      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: response.content },
      ]);

      if (response.summary_ready) {
        setSummaryReady(true);
      }
    } catch (err) {
      console.error('Feedback chat error:', err);
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Sorry, something went wrong. Please try again.' },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleSendCorrection = async () => {
    const trimmed = input.trim();
    if (!trimmed || loading) return;

    // Send correction as a regular message - AI will revise the summary
    setSummaryReady(false);
    await handleSend();
  };

  const handleSubmitFeedback = async () => {
    const lastAssistantMsg = [...messages].reverse().find((m) => m.role === 'assistant');
    if (!lastAssistantMsg) return;

    const categoryMatch = lastAssistantMsg.content.match(/\*\*Category:\*\*\s*(.+)/);
    const issueMatch = lastAssistantMsg.content.match(/\*\*Issue:\*\*\s*(.+)/);
    const severityMatch = lastAssistantMsg.content.match(/\*\*Severity:\*\*\s*(.+)/);

    try {
      await api.submitFeedback({
        category: categoryMatch?.[1]?.trim() || 'Other',
        summary: issueMatch?.[1]?.trim() || lastAssistantMsg.content,
        severity: severityMatch?.[1]?.trim() || 'Medium',
        raw_conversation: messages.map(({ role, content }) => ({ role, content })),
      });
      setSubmitted(true);
      setTimeout(onClose, 2000);
    } catch (err) {
      console.error('Failed to submit feedback:', err);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div
      className="fixed bottom-20 right-6 z-[60] w-[360px] h-[450px] bg-white rounded-lg shadow-2xl border flex flex-col"
      data-testid="feedback-popover"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b bg-blue-600 rounded-t-lg">
        <h3 className="text-white font-medium">Share Feedback</h3>
        <button
          onClick={onClose}
          className="text-blue-200 hover:text-white"
          data-testid="feedback-popover-close"
          aria-label="Close feedback"
        >
          <FiX size={18} />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {submitted ? (
          <div className="text-center py-8">
            <p className="text-lg font-medium text-gray-900">Thank you for your feedback!</p>
          </div>
        ) : (
          <>
            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[80%] px-3 py-2 rounded-lg text-sm ${
                    msg.role === 'user'
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-100 text-gray-800'
                  }`}
                >
                  {msg.content}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="bg-gray-100 px-3 py-2 rounded-lg text-sm text-gray-500">
                  Typing...
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input / Submit */}
      {!submitted && (
        <div className="border-t p-3">
          {summaryReady ? (
            <div className="space-y-2">
              <button
                onClick={handleSubmitFeedback}
                className="w-full py-2 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700 transition-colors"
                data-testid="feedback-submit"
              >
                Submit Feedback
              </button>
              <div className="flex gap-2">
                <input
                  ref={inputRef}
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Or type a correction..."
                  className="flex-1 px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  data-testid="feedback-correction-input"
                  disabled={loading}
                />
                <button
                  onClick={handleSendCorrection}
                  disabled={!input.trim() || loading}
                  className="px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
                  data-testid="feedback-correction-send"
                  aria-label="Send correction"
                >
                  <FiSend size={16} />
                </button>
              </div>
            </div>
          ) : (
            <div className="flex gap-2">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Type your feedback..."
                className="flex-1 px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                data-testid="feedback-input"
                disabled={loading}
                autoFocus
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || loading}
                className="px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
                data-testid="feedback-send"
                aria-label="Send message"
              >
                <FiSend size={16} />
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

import { useState, useRef, useEffect } from 'react';
import { ArrowUp, PanelLeft, Sparkles } from 'lucide-react';
import { sendMessage } from '../lib/api';
import ChatMessage from './ChatMessage';

const SUGGESTED_PROMPTS = [
  { icon: '🎯', text: 'What does Lenny say about product-market fit?' },
  { icon: '📈', text: 'How should I think about user retention?' },
  { icon: '✍️', text: 'Write a Ship 30 essay about growth loops' },
  { icon: '🚀', text: 'What metrics matter most for early-stage products?' },
];

export default function ChatPanel({
  sessionId, messages, loading, setLoading,
  onNewMessage, onStartSession, modelConfig,
  sidebarOpen, onToggleSidebar, onOpenArtifact,
}) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  useEffect(() => {
    if (sessionId) inputRef.current?.focus();
  }, [sessionId]);

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px';
  }, [input]);

  async function handleSubmit(e) {
    e?.preventDefault();
    const content = input.trim();
    if (!content || loading) return;

    // If no session yet, create one first
    if (!sessionId) {
      await onStartSession();
      // The session creation is async, so the parent will re-render with the new sessionId
      // We need to submit after session is created — handled by parent via useEffect
      return;
    }

    setInput('');
    setLoading(true);

    const userMsg = {
      id: crypto.randomUUID(),
      session_id: sessionId,
      role: 'user',
      content,
      sources: [],
      artifact: null,
      model_used: null,
      created_at: new Date().toISOString(),
    };

    try {
      const response = await sendMessage(sessionId, content);
      onNewMessage(userMsg, response);
    } catch (err) {
      onNewMessage(userMsg, {
        message: {
          id: crypto.randomUUID(),
          session_id: sessionId,
          role: 'assistant',
          content: `I encountered an error: ${err.message}. Please try again.`,
          sources: [],
          artifact: null,
          model_used: 'error',
          created_at: new Date().toISOString(),
        },
      });
    } finally {
      setLoading(false);
    }
  }

  async function handleSuggestion(text) {
    setInput(text);
    if (!sessionId) {
      await onStartSession();
    }
    // Submit after a tick to allow state to settle
    setTimeout(() => {
      handleSubmitText(text);
    }, 50);
  }

  async function handleSubmitText(content) {
    if (!content.trim() || loading || !sessionId) return;
    setInput('');
    setLoading(true);

    const userMsg = {
      id: crypto.randomUUID(),
      session_id: sessionId,
      role: 'user',
      content: content.trim(),
      sources: [],
      artifact: null,
      model_used: null,
      created_at: new Date().toISOString(),
    };

    try {
      const response = await sendMessage(sessionId, content.trim());
      onNewMessage(userMsg, response);
    } catch (err) {
      onNewMessage(userMsg, {
        message: {
          id: crypto.randomUUID(),
          session_id: sessionId,
          role: 'assistant',
          content: `Error: ${err.message}`,
          sources: [],
          artifact: null,
          model_used: 'error',
          created_at: new Date().toISOString(),
        },
      });
    } finally {
      setLoading(false);
    }
  }

  // Empty welcome state
  if (!sessionId || messages.length === 0) {
    return (
      <div className="h-full flex flex-col" style={{ background: '#fafaf8' }}>
        {/* Top bar when sidebar is closed */}
        {!sidebarOpen && (
          <div className="flex items-center px-4 py-3 flex-shrink-0">
            <button
              onClick={onToggleSidebar}
              className="p-1.5 rounded-md transition-colors"
              style={{ color: '#8a8880' }}
              onMouseEnter={e => e.currentTarget.style.background = '#eeede8'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              aria-label="Open sidebar"
            >
              <PanelLeft size={18} />
            </button>
          </div>
        )}

        {/* Welcome screen — centered */}
        <div className="flex-1 flex flex-col items-center justify-center px-6 pb-32">
          {/* Logo */}
          <div
            className="w-12 h-12 rounded-2xl flex items-center justify-center text-white text-xl font-bold mb-6 shadow-sm"
            style={{ background: 'linear-gradient(135deg, #d97706, #f59e0b)' }}
          >
            L
          </div>

          <h1 className="text-2xl font-semibold mb-2 text-center" style={{ color: '#1a1916' }}>
            Lenny Growth Assistant
          </h1>
          <p className="text-sm text-center max-w-sm mb-10" style={{ color: '#8a8880', lineHeight: 1.6 }}>
            Ask questions grounded in Lenny's Podcast, write Ship 30 essays,
            or generate documents — all sourced from 303 transcripts.
          </p>

          {/* Suggestion cards */}
          <div className="grid grid-cols-2 gap-2 w-full max-w-lg mb-10">
            {SUGGESTED_PROMPTS.map(({ icon, text }) => (
              <button
                key={text}
                onClick={() => {
                  if (sessionId) {
                    setInput(text);
                    inputRef.current?.focus();
                  } else {
                    onStartSession().then(() => setInput(text));
                  }
                }}
                className="text-left px-4 py-3 rounded-xl text-sm transition-all border"
                style={{
                  background: '#ffffff',
                  borderColor: '#e8e7e1',
                  color: '#44433e',
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.background = '#f4f4ef';
                  e.currentTarget.style.borderColor = '#d4d3cc';
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.background = '#ffffff';
                  e.currentTarget.style.borderColor = '#e8e7e1';
                }}
              >
                <span className="mr-2">{icon}</span>
                {text}
              </button>
            ))}
          </div>
        </div>

        {/* Fixed input at bottom */}
        <div className="flex-shrink-0 px-4 pb-6">
          <InputBox
            ref={inputRef}
            textareaRef={textareaRef}
            input={input}
            setInput={setInput}
            loading={loading}
            onSubmit={handleSubmit}
            onStartSession={onStartSession}
            sessionId={sessionId}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col" style={{ background: '#fafaf8' }}>
      {/* Minimal top bar when sidebar is collapsed */}
      {!sidebarOpen && (
        <div className="flex items-center px-4 py-3 flex-shrink-0">
          <button
            onClick={onToggleSidebar}
            className="p-1.5 rounded-md transition-colors"
            style={{ color: '#8a8880' }}
            onMouseEnter={e => e.currentTarget.style.background = '#eeede8'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            aria-label="Open sidebar"
          >
            <PanelLeft size={18} />
          </button>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-chat mx-auto px-4 py-6 space-y-0">
          {messages.map((msg, i) => (
            <ChatMessage
              key={msg.id}
              message={msg}
              isLast={i === messages.length - 1}
              onOpenArtifact={onOpenArtifact}
            />
          ))}

          {/* Typing indicator */}
          {loading && (
            <div className="flex gap-4 py-6 fade-in">
              <div
                className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5"
                style={{ background: 'linear-gradient(135deg, #d97706, #f59e0b)' }}
              >
                <Sparkles size={14} className="text-white" />
              </div>
              <div className="flex items-center gap-1.5 pt-2">
                <div className="loading-dot" />
                <div className="loading-dot" />
                <div className="loading-dot" />
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input bar */}
      <div className="flex-shrink-0 px-4 pb-5 pt-2">
        <div className="max-w-chat mx-auto">
          <InputBox
            ref={inputRef}
            textareaRef={textareaRef}
            input={input}
            setInput={setInput}
            loading={loading}
            onSubmit={handleSubmit}
            sessionId={sessionId}
          />
          <p className="text-center text-[11px] mt-2" style={{ color: '#b5b3ae' }}>
            {modelConfig
              ? `${modelConfig.active_provider} · ${modelConfig.active_model} · `
              : ''}
            Grounded in Lenny's Podcast transcripts
          </p>
        </div>
      </div>
    </div>
  );
}

// Extracted input box component — uses forwardRef so parent can focus the textarea
import { forwardRef } from 'react';

const InputBox = forwardRef(function InputBox({ textareaRef, input, setInput, loading, onSubmit }, ref) {
  const canSubmit = input.trim().length > 0 && !loading;

  return (
    <div
      className="relative rounded-2xl border transition-all"
      style={{
        background: '#ffffff',
        borderColor: '#d4d3cc',
        boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
      }}
    >
      <textarea
        ref={el => {
          if (textareaRef) textareaRef.current = el;
          if (ref) {
            if (typeof ref === 'function') ref(el);
            else ref.current = el;
          }
        }}
        value={input}
        onChange={e => setInput(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            onSubmit(e);
          }
        }}
        placeholder="Message Lenny AI…"
        rows={1}
        disabled={loading}
        className="w-full bg-transparent outline-none text-sm px-4 pt-3.5 pb-12 resize-none"
        style={{
          color: '#1a1916',
          minHeight: '52px',
          maxHeight: '200px',
          caretColor: '#d97706',
        }}
        aria-label="Message input"
      />

      {/* Bottom row of input */}
      <div className="absolute bottom-3 right-3 flex items-center gap-2">
        <button
          type="button"
          onClick={onSubmit}
          disabled={!canSubmit}
          className="w-8 h-8 rounded-lg flex items-center justify-center transition-all"
          style={{
            background: canSubmit ? '#1a1916' : '#e8e7e1',
            color: canSubmit ? '#ffffff' : '#b5b3ae',
            cursor: canSubmit ? 'pointer' : 'not-allowed',
          }}
          aria-label="Send message"
        >
          <ArrowUp size={16} strokeWidth={2.5} />
        </button>
      </div>
    </div>
  );
});

import { useState, useEffect, useRef } from 'react';
import { Plus, MessageSquare, Trash2, PanelLeftClose, ChevronDown, Check, Loader2 } from 'lucide-react';
import { listProviders, switchProvider } from '../lib/api';

export default function Sidebar({
  sessions, activeSessionId, onSelectSession, onNewSession,
  onDeleteSession, onToggleSidebar, modelConfig, onModelChange,
}) {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [providers, setProviders] = useState([]);
  const [switching, setSwitching] = useState(false);
  const dropdownRef = useRef(null);

  const activeProvider = modelConfig?.active_provider || 'ollama';
  const activeModel = modelConfig?.active_model || '…';

  // Load available providers on mount
  useEffect(() => {
    listProviders()
      .then(data => setProviders(data.providers || []))
      .catch(() => {});
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  async function handleSwitch(providerId) {
    if (providerId === activeProvider || switching) return;
    setDropdownOpen(false);
    setSwitching(true);
    try {
      const result = await switchProvider(providerId);
      if (onModelChange) {
        onModelChange({
          active_provider: result.active_provider,
          active_model: result.active_model,
        });
      }
    } catch (err) {
      console.error('Provider switch failed:', err);
    } finally {
      setSwitching(false);
    }
  }

  // Provider display names
  const PROVIDER_LABELS = {
    ollama: 'Ollama',
    anthropic: 'Claude',
    openai: 'OpenAI',
  };

  const PROVIDER_COLORS = {
    ollama: '#6366f1',    // indigo for local
    anthropic: '#d97706', // amber for Claude
    openai: '#10b981',    // green for OpenAI
  };

  const accentColor = PROVIDER_COLORS[activeProvider] || '#d97706';

  return (
    <div className="h-full flex flex-col" style={{ background: '#f0efeb' }}>
      {/* Sidebar Header */}
      <div className="flex items-center justify-between px-3 pt-4 pb-2">
        <div className="flex items-center gap-2 px-1">
          <div
            className="w-6 h-6 rounded-md flex items-center justify-center text-white text-xs font-bold"
            style={{ background: '#d97706' }}
          >
            L
          </div>
          <span className="text-sm font-semibold" style={{ color: '#1a1916' }}>
            Lenny AI
          </span>
        </div>
        <button
          onClick={onToggleSidebar}
          className="p-1.5 rounded-md transition-colors"
          style={{ color: '#8a8880' }}
          onMouseEnter={e => e.currentTarget.style.background = '#e8e7e1'}
          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          aria-label="Close sidebar"
        >
          <PanelLeftClose size={16} />
        </button>
      </div>

      {/* New Chat */}
      <div className="px-2 pb-2">
        <button
          onClick={onNewSession}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors text-left"
          style={{ color: '#44433e' }}
          onMouseEnter={e => e.currentTarget.style.background = '#e8e7e1'}
          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
        >
          <Plus size={15} strokeWidth={2} />
          New chat
        </button>
      </div>

      {/* Divider */}
      <div style={{ height: '1px', background: '#d8d7d0', margin: '0 12px 8px' }} />

      {/* Sessions label */}
      {sessions.length > 0 && (
        <div className="px-4 pb-1">
          <span className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: '#b5b3ae' }}>
            Recents
          </span>
        </div>
      )}

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-2 space-y-0.5">
        {sessions.length === 0 ? (
          <div className="px-4 py-6 text-center">
            <p className="text-xs" style={{ color: '#b5b3ae' }}>No conversations yet</p>
            <p className="text-xs mt-1" style={{ color: '#b5b3ae' }}>Start one below ↑</p>
          </div>
        ) : (
          sessions.map(session => {
            const isActive = activeSessionId === session.id;
            return (
              <div
                key={session.id}
                className="group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors"
                style={{
                  background: isActive ? '#e2e1da' : 'transparent',
                  color: isActive ? '#1a1916' : '#44433e',
                }}
                onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = '#e8e7e1'; }}
                onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                onClick={() => onSelectSession(session.id)}
              >
                <MessageSquare size={13} style={{ flexShrink: 0, opacity: 0.6 }} />
                <span className="truncate flex-1 text-sm">
                  {session.title || 'New conversation'}
                </span>
                <button
                  onClick={e => { e.stopPropagation(); onDeleteSession(session.id); }}
                  className="opacity-0 group-hover:opacity-100 p-1 rounded transition-all"
                  style={{ color: '#8a8880' }}
                  onMouseEnter={e => { e.currentTarget.style.color = '#ef4444'; }}
                  onMouseLeave={e => { e.currentTarget.style.color = '#8a8880'; }}
                  aria-label="Delete conversation"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* Model Picker at bottom */}
      <div className="px-3 py-3 border-t" style={{ borderColor: '#d8d7d0' }} ref={dropdownRef}>
        {/* Trigger button */}
        <button
          onClick={() => setDropdownOpen(v => !v)}
          disabled={switching}
          className="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-left transition-all"
          style={{
            background: dropdownOpen ? '#e2e1da' : '#e8e7e1',
            border: `1.5px solid ${dropdownOpen ? accentColor + '60' : 'transparent'}`,
          }}
          onMouseEnter={e => { if (!dropdownOpen) e.currentTarget.style.background = '#e2e1da'; }}
          onMouseLeave={e => { if (!dropdownOpen) e.currentTarget.style.background = '#e8e7e1'; }}
          aria-label="Switch model"
        >
          {/* Colored dot */}
          <span
            className="w-2 h-2 rounded-full flex-shrink-0"
            style={{ background: switching ? '#b5b3ae' : accentColor }}
          />
          <span className="flex-1 min-w-0">
            <span className="text-xs font-medium block truncate" style={{ color: '#1a1916' }}>
              {PROVIDER_LABELS[activeProvider] || activeProvider}
            </span>
            <span className="text-[10px] block truncate" style={{ color: '#8a8880' }}>
              {activeModel}
            </span>
          </span>
          {switching
            ? <Loader2 size={12} className="animate-spin flex-shrink-0" style={{ color: '#8a8880' }} />
            : <ChevronDown
                size={12}
                className="flex-shrink-0 transition-transform"
                style={{ color: '#8a8880', transform: dropdownOpen ? 'rotate(180deg)' : 'rotate(0deg)' }}
              />
          }
        </button>

        {/* Dropdown */}
        {dropdownOpen && (
          <div
            className="absolute bottom-16 left-3 right-3 rounded-xl shadow-lg overflow-hidden z-50"
            style={{
              background: '#fafaf8',
              border: '1px solid #e2e1da',
              boxShadow: '0 8px 24px rgba(0,0,0,0.12)',
            }}
          >
            <div className="px-3 py-2 border-b" style={{ borderColor: '#e8e7e1' }}>
              <span className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: '#b5b3ae' }}>
                Switch model
              </span>
            </div>
            {providers.map(p => {
              const isActive = p.id === activeProvider;
              const color = PROVIDER_COLORS[p.id] || '#8a8880';
              return (
                <button
                  key={p.id}
                  onClick={() => handleSwitch(p.id)}
                  disabled={!p.configured || isActive}
                  className="w-full flex items-center gap-3 px-3 py-2.5 text-left transition-colors"
                  style={{
                    background: isActive ? '#f0efeb' : 'transparent',
                    opacity: p.configured ? 1 : 0.45,
                    cursor: p.configured && !isActive ? 'pointer' : 'default',
                  }}
                  onMouseEnter={e => { if (p.configured && !isActive) e.currentTarget.style.background = '#f0efeb'; }}
                  onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                >
                  <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
                  <span className="flex-1 min-w-0">
                    <span className="text-xs font-medium block" style={{ color: '#1a1916' }}>
                      {PROVIDER_LABELS[p.id] || p.id}
                    </span>
                    <span className="text-[10px] block truncate" style={{ color: '#8a8880' }}>
                      {p.model}
                      {!p.configured && p.requires_key && ' · API key not set'}
                    </span>
                  </span>
                  {isActive && <Check size={12} style={{ color: accentColor, flexShrink: 0 }} />}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

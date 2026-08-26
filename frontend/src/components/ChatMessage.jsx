import { useState } from 'react';
import { User, Sparkles, ChevronDown, ChevronUp, BookOpen, Copy, Check, PanelRight, FileText } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export default function ChatMessage({ message, isLast, onOpenArtifact }) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const isUser = message.role === 'user';
  const hasSources = message.sources && message.sources.length > 0;

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* silent */ }
  }

  if (isUser) {
    return (
      <div className="flex justify-end py-3 fade-in">
        <div
          className="max-w-[80%] px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap"
          style={{
            background: '#eeede8',
            color: '#1a1916',
            borderBottomRightRadius: '6px',
          }}
        >
          {message.content}
        </div>
      </div>
    );
  }

  // Assistant message
  return (
    <div className="group flex gap-4 py-5 fade-in">
      {/* Avatar */}
      <div
        className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5"
        style={{ background: 'linear-gradient(135deg, #d97706, #f59e0b)' }}
      >
        <Sparkles size={14} className="text-white" />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 pt-0.5">
        {/* Markdown body */}
        <div className="text-sm prose-chat">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {message.content}
          </ReactMarkdown>
        </div>

        {/* Artifact re-open button */}
        {message.artifact && onOpenArtifact && (
          <div className="mt-3">
            <button
              onClick={() => onOpenArtifact(message.artifact)}
              className="flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium border transition-all"
              style={{
                background: '#fef9f0',
                borderColor: '#fde68a',
                color: '#92400e',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.background = '#fef3c7';
                e.currentTarget.style.borderColor = '#fbbf24';
              }}
              onMouseLeave={e => {
                e.currentTarget.style.background = '#fef9f0';
                e.currentTarget.style.borderColor = '#fde68a';
              }}
            >
              <FileText size={12} />
              Open {message.artifact.type === 'html' ? 'HTML artifact' : 'document'}
              <PanelRight size={12} style={{ marginLeft: 2, opacity: 0.7 }} />
            </button>
          </div>
        )}

        {/* Sources */}
        {hasSources && (
          <div className="mt-3">
            <button
              onClick={() => setSourcesOpen(!sourcesOpen)}
              className="flex items-center gap-1.5 text-xs py-1 px-2 rounded-lg transition-colors"
              style={{ color: '#8a8880', background: 'transparent' }}
              onMouseEnter={e => e.currentTarget.style.background = '#f0efeb'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              <BookOpen size={11} />
              <span>
                {message.sources.length} source{message.sources.length !== 1 ? 's' : ''}
              </span>
              {sourcesOpen ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
            </button>

            {sourcesOpen && (
              <div className="mt-2 space-y-2 fade-in">
                {message.sources.map((source, i) => (
                  <div
                    key={i}
                    className="text-xs rounded-xl p-3 border"
                    style={{
                      background: '#fafaf8',
                      borderColor: '#e8e7e1',
                    }}
                  >
                    <div className="flex items-start justify-between gap-2 mb-1">
                      <span className="font-medium" style={{ color: '#44433e' }}>
                        {source.metadata?.title || source.transcript}
                      </span>
                      <span
                        className="flex-shrink-0 text-[10px] px-1.5 py-0.5 rounded-full font-medium"
                        style={{ background: '#fef3c7', color: '#92400e' }}
                      >
                        {(source.relevance_score * 100).toFixed(0)}% match
                      </span>
                    </div>
                    {source.metadata?.guest && (
                      <p className="mb-1" style={{ color: '#8a8880' }}>
                        Guest: {source.metadata.guest}
                      </p>
                    )}
                    <p className="leading-relaxed line-clamp-3" style={{ color: '#8a8880' }}>
                      {source.text}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Copy button — visible on hover */}
        <div className="mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 text-xs px-2 py-1 rounded-lg transition-colors"
            style={{ color: '#b5b3ae' }}
            onMouseEnter={e => e.currentTarget.style.color = '#44433e'}
            onMouseLeave={e => e.currentTarget.style.color = '#b5b3ae'}
          >
            {copied ? (
              <><Check size={11} style={{ color: '#16a34a' }} /> Copied</>
            ) : (
              <><Copy size={11} /> Copy</>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

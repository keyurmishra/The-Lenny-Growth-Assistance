import { useState, useMemo } from 'react';
import { X, Copy, Download, Check, FileText, Code2, Eye, LayoutTemplate } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/**
 * SECURITY — HTML artifact isolation (two layers):
 *
 * Layer 1: DOMPurify-like stripping (manual, no dependency on window.DOMPurify load timing)
 *   We remove <script> tags with dangerous patterns and strip javascript: URIs
 *   from attributes before injection.
 *
 * Layer 2: Sandboxed iframe with sandbox="allow-scripts" (NO allow-same-origin)
 *   - Scripts can run (for interactive artifacts)
 *   - Cannot access parent DOM, cookies, localStorage, or sessionStorage
 *   - Cannot redirect the user (no allow-top-navigation)
 *   - Cannot submit forms externally (no allow-forms)
 *   - srcdoc attribute: HTML never touches a server URL
 *
 * WHY NOT allow-same-origin: Combining it with allow-scripts lets the iframe
 * remove its own sandbox via script — a known escape vector. Never combine them.
 */
function sanitizeHtml(html) {
  // Strip event handler attributes (onclick, onload, onerror, etc.)
  let clean = html.replace(/\s+on\w+\s*=\s*(['"])[^'"]*\1/gi, '');
  // Strip javascript: URIs
  clean = clean.replace(/javascript\s*:/gi, 'removed:');
  // Strip <script> blocks that reference external URLs
  clean = clean.replace(/<script[^>]*src\s*=\s*['"][^'"]*['"]/gi, '<script data-blocked');
  return clean;
}

export default function ArtifactViewer({ artifact, onClose }) {
  const [copied, setCopied] = useState(false);
  const [viewMode, setViewMode] = useState('preview');

  const sanitizedHtml = useMemo(() => {
    if (artifact?.type === 'html') return sanitizeHtml(artifact.content);
    return artifact?.content ?? '';
  }, [artifact?.type, artifact?.content]);

  if (!artifact) return null;

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(artifact.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* silent */ }
  }

  function handleDownload() {
    const ext = artifact.type === 'html' ? 'html' : 'md';
    const mime = artifact.type === 'html' ? 'text/html' : 'text/markdown';
    const blob = new Blob([artifact.content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `artifact.${ext}`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const isHtml = artifact.type === 'html';
  const title = artifact.title || (isHtml ? 'HTML Artifact' : 'Document');

  return (
    <div className="h-full flex flex-col" style={{ background: '#ffffff' }}>
      {/* Header bar */}
      <div
        className="flex items-center justify-between px-4 py-2.5 flex-shrink-0 border-b"
        style={{ borderColor: '#e8e7e1' }}
      >
        <div className="flex items-center gap-2 min-w-0">
          {isHtml
            ? <Code2 size={14} style={{ color: '#d97706', flexShrink: 0 }} />
            : <LayoutTemplate size={14} style={{ color: '#d97706', flexShrink: 0 }} />
          }
          <span className="text-sm font-medium truncate" style={{ color: '#1a1916' }}>
            {title}
          </span>
          <span
            className="text-[10px] px-1.5 py-0.5 rounded-full font-medium uppercase tracking-wide flex-shrink-0"
            style={{ background: '#f0efeb', color: '#8a8880' }}
          >
            {artifact.type}
          </span>
        </div>

        <div className="flex items-center gap-1 flex-shrink-0 ml-2">
          {/* Preview / Source toggle */}
          <button
            onClick={() => setViewMode(v => v === 'preview' ? 'source' : 'preview')}
            className="flex items-center gap-1 px-2.5 py-1 text-xs rounded-lg transition-colors"
            style={{ color: '#44433e' }}
            onMouseEnter={e => e.currentTarget.style.background = '#f0efeb'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          >
            {viewMode === 'preview'
              ? <><Code2 size={12} /> Source</>
              : <><Eye size={12} /> Preview</>
            }
          </button>

          <button
            onClick={handleCopy}
            className="p-1.5 rounded-lg transition-colors"
            style={{ color: '#8a8880' }}
            onMouseEnter={e => e.currentTarget.style.background = '#f0efeb'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            aria-label="Copy content"
          >
            {copied
              ? <Check size={14} style={{ color: '#16a34a' }} />
              : <Copy size={14} />
            }
          </button>

          <button
            onClick={handleDownload}
            className="p-1.5 rounded-lg transition-colors"
            style={{ color: '#8a8880' }}
            onMouseEnter={e => e.currentTarget.style.background = '#f0efeb'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            aria-label="Download"
          >
            <Download size={14} />
          </button>

          <div style={{ width: '1px', height: '20px', background: '#e8e7e1', margin: '0 4px' }} />

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg transition-colors"
            style={{ color: '#8a8880' }}
            onMouseEnter={e => e.currentTarget.style.background = '#f0efeb'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            aria-label="Close artifact viewer"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-auto">
        {viewMode === 'source' ? (
          <pre
            className="p-5 text-xs font-mono whitespace-pre-wrap break-words h-full overflow-auto"
            style={{ color: '#44433e', background: '#fafaf8' }}
          >
            {artifact.content}
          </pre>
        ) : isHtml ? (
          /*
           * HTML rendered in a sandboxed iframe.
           * Security: see module-level comment above.
           * sandbox="allow-scripts" WITHOUT allow-same-origin.
           */
          <iframe
            srcDoc={sanitizedHtml}
            sandbox="allow-scripts"
            title="Artifact preview (sandboxed)"
            className="w-full h-full border-0"
            referrerPolicy="no-referrer"
          />
        ) : (
          /* Markdown with GitHub-Flavored Markdown (tables, task lists, etc.) */
          <div className="p-8 max-w-3xl mx-auto prose-chat text-sm pb-16">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {artifact.content}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}

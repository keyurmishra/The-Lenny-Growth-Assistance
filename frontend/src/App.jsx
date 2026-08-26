import { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import ChatPanel from './components/ChatPanel';
import ArtifactViewer from './components/ArtifactViewer';
import { listSessions, createSession, deleteSession, getMessages, getModelConfig } from './lib/api';

export default function App() {
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [artifact, setArtifact] = useState(null);
  const [modelConfig, setModelConfig] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadSessions();
    loadModelConfig();
  }, []);

  useEffect(() => {
    if (activeSessionId) {
      loadMessages(activeSessionId);
      setArtifact(null);
    }
  }, [activeSessionId]);

  async function loadSessions() {
    try {
      const data = await listSessions();
      setSessions(data.sessions || []);
    } catch (err) {
      console.error('Failed to load sessions:', err);
    }
  }

  async function loadModelConfig() {
    try {
      const config = await getModelConfig();
      setModelConfig(config);
    } catch (err) {
      console.error('Failed to load model config:', err);
    }
  }

  async function loadMessages(sessionId) {
    try {
      const msgs = await getMessages(sessionId);
      setMessages(msgs || []);
      const lastArtifact = [...(msgs || [])].reverse().find(m => m.artifact);
      if (lastArtifact?.artifact) setArtifact(lastArtifact.artifact);
    } catch (err) {
      console.error('Failed to load messages:', err);
    }
  }

  async function handleNewSession() {
    try {
      const session = await createSession();
      setSessions(prev => [session, ...prev]);
      setActiveSessionId(session.id);
      setMessages([]);
      setArtifact(null);
    } catch (err) {
      console.error('Failed to create session:', err);
    }
  }

  async function handleDeleteSession(sessionId) {
    try {
      await deleteSession(sessionId);
      setSessions(prev => prev.filter(s => s.id !== sessionId));
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
        setMessages([]);
        setArtifact(null);
      }
    } catch (err) {
      console.error('Failed to delete session:', err);
    }
  }

  function handleNewMessage(userMsg, assistantResponse) {
    setMessages(prev => [...prev, userMsg, assistantResponse.message]);
    setSessions(prev => prev.map(s =>
      s.id === activeSessionId
        ? { ...s, title: s.title || userMsg.content.slice(0, 60), message_count: (s.message_count || 0) + 2 }
        : s
    ));
    if (assistantResponse.message?.artifact) {
      setArtifact(assistantResponse.message.artifact);
    }
  }

  const showArtifact = !!artifact;

  return (
    <div className="h-screen flex overflow-hidden" style={{ background: '#fafaf8' }}>
      {/* Sidebar */}
      <div
        className="flex-shrink-0 overflow-hidden transition-all duration-200 ease-in-out"
        style={{
          width: sidebarOpen ? '260px' : '0px',
          background: '#f0efeb',
          borderRight: sidebarOpen ? '1px solid #d8d7d0' : 'none',
        }}
      >
        <Sidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={setActiveSessionId}
          onNewSession={handleNewSession}
          onDeleteSession={handleDeleteSession}
          onToggleSidebar={() => setSidebarOpen(false)}
          modelConfig={modelConfig}
          onModelChange={setModelConfig}
        />
      </div>

      {/* Main area */}
      <div className="flex-1 flex overflow-hidden min-w-0">
        {/* Chat panel */}
        <div className={`flex flex-col overflow-hidden transition-all duration-200 ${showArtifact ? 'w-1/2' : 'flex-1'}`}
          style={{ background: '#fafaf8' }}
        >
          <ChatPanel
            sessionId={activeSessionId}
            messages={messages}
            loading={loading}
            setLoading={setLoading}
            onNewMessage={handleNewMessage}
            onStartSession={handleNewSession}
            modelConfig={modelConfig}
            sidebarOpen={sidebarOpen}
            onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
            onOpenArtifact={setArtifact}
          />
        </div>

        {/* Artifact panel */}
        {showArtifact && (
          <div
            className="flex-shrink-0 overflow-hidden"
            style={{
              width: '50%',
              borderLeft: '1px solid #e8e7e1',
              background: '#ffffff',
            }}
          >
            <ArtifactViewer
              artifact={artifact}
              onClose={() => setArtifact(null)}
            />
          </div>
        )}
      </div>
    </div>
  );
}

import React, { useState } from 'react';
import './App.css';

function App() {
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [url, setUrl] = useState('');

const fetchSummary = async () => {
  if (!url.trim()) {
    setError('Please enter a valid URL');
    return;
  }
  setLoading(true);
  setError(null);
  try {
    const response = await fetch('https://thriving-ambition.up.railway.app/download', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ youtube_url: url }),
});
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || 'Error');
    setSummary(data.summary);
  } catch (err) {
    setError(err.message);
  } finally {
    setLoading(false);
  }
};

  const toggleSection = (e) => {
    const section = e.currentTarget;
    section.classList.toggle('collapsed');
    section.classList.toggle('expanded');
  };

  return (
    <div className="flex items-center justify-center min-h-screen p-4">
      <div className="container p-4 rounded-lg w-full max-w-lg text-center">
        <h1 className="text-2xl font-semibold mb-2 text-pulse-gray">Podcast Pulse</h1>
        <p className="text-sm mb-2 text-pulse-gray/70">Discover wisdom from podcasts.</p>
        <input
          id="urlInput"
          type="text"
          placeholder="Paste YouTube URL"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          className="w-full p-2 mb-2 border border-pulse-border rounded-lg bg-white text-pulse-gray focus:outline-none focus:ring-1 focus:ring-pulse-blue"
          aria-required="true"
        />
        <button
          onClick={fetchSummary}
          className="w-full bg-pulse-blue text-white p-2 rounded-lg hover:bg-pulse-blue/90 transition duration-150"
          aria-label="Extract Insights"
        >
          Extract Wisdom
        </button>
        {loading && <div id="loading" className="text-center text-pulse-blue">Processing...</div>}
        {error && <div id="error" className="text-red-600">{error}</div>}
        {summary && (
          <div id="summary">
            <div id="podcastTitle" className="mb-2 p-2 bg-white rounded-lg">
              <h2 className="text-lg font-medium text-pulse-gray">{summary.title || 'No title'}</h2>
            </div>
            <div id="pulseCore" className="pulse-core mb-2 p-2 rounded-full">
              <h2 className="text-base font-medium text-pulse-gray">Core of Wisdom</h2>
            </div>
            <div id="topics" className="section mb-2 p-2 bg-white rounded-lg" onClick={toggleSection}>
              <h3 className="text-base font-medium text-pulse-gray">Core Topics</h3>
              <ul className="list-disc pl-4 mt-1">{(summary.topics || []).map((t) => (
                <li key={t.name}>{t.name}: {t.quotes_advice.join(', ')}</li>
              ))}</ul>
            </div>
            <div id="resources" className="section mb-2 p-2 bg-white rounded-lg" onClick={toggleSection}>
              <h3 className="text-base font-medium text-pulse-gray">Resources</h3>
              <ul className="list-disc pl-4 mt-1">{(summary.resources || []).map((r, i) => (
                <li key={i}>{r}</li>
              ))}</ul>
            </div>
            <div id="keyQuestions" className="section mt-2 p-2 bg-white rounded-lg" onClick={toggleSection}>
              <h3 className="text-base font-medium text-pulse-gray">Key Questions</h3>
              <ul className="list-disc pl-4 mt-1">{(summary.key_questions || []).map((q, i) => (
                <li key={i}>{q}</li>
              ))}</ul>
            </div>
          </div>
        )}
        <div id="feedback" className="mt-2">
          <textarea
            id="feedbackInput"
            placeholder="Share your thoughts..."
            className="w-full p-1 mb-1 border border-pulse-border rounded-lg bg-white text-pulse-gray focus:outline-none focus:ring-1 focus:ring-pulse-blue"
            rows="2"
          ></textarea>
          <button
            id="submitFeedback"
            className="w-full bg-pulse-blue text-white p-1 rounded-lg hover:bg-pulse-blue/90 transition duration-150"
            aria-label="Submit Feedback"
          >
            Send Feedback
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;
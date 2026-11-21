const quickQuestions = [
  "Summarize the key points",
  "What are the main topics discussed?",
  "Who are the speakers?",
  "What decisions were made?",
];

const SUGGESTION_ICONS = [
  "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
  "M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z",
  "M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z",
  "M5 13l4 4L19 7",
];

interface ChatSuggestionsProps {
  sendMessage: (question: string) => void;
}

export const ChatSuggestions: React.FC<ChatSuggestionsProps> = ({ sendMessage }) => (
    <div className="sug-list">
      <div className="sug-list-label">Try asking</div>
      {quickQuestions.map((question, index) => {
        return (
          <button
            key={index}
            onClick={() => sendMessage(question)}
            className="sug"
          >
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d={SUGGESTION_ICONS[index % SUGGESTION_ICONS.length]} />
            </svg>
            {question}
          </button>
        );
      })}
    </div>
);

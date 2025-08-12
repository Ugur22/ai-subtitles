import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TranscriptionUpload } from "./components/features/transcription/TranscriptionUpload";

const queryClient = new QueryClient();

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <div className="mx-auto max-w-8xl px-4 sm:px-6 lg:px-8">
        <TranscriptionUpload />
      </div>
    </QueryClientProvider>
  );
}

export default App;

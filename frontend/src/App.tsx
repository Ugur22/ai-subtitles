import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TranscriptionUpload } from "./components/features/transcription/TranscriptionUpload";

const queryClient = new QueryClient();

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TranscriptionUpload />
    </QueryClientProvider>
  );
}

export default App;

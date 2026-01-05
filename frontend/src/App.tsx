import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TranscriptionUpload } from "./components/features/transcription/TranscriptionUpload";
import { PasswordGate } from "./components/auth/PasswordGate";

const queryClient = new QueryClient();

function App() {
  return (
    <PasswordGate>
      <QueryClientProvider client={queryClient}>
        <div className="w-full">
          <TranscriptionUpload />
        </div>
      </QueryClientProvider>
    </PasswordGate>
  );
}

export default App;

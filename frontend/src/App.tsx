import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TranscriptionUpload } from "./components/features/transcription/TranscriptionUpload";
import { StagewiseToolbar } from "@stagewise/toolbar-react";
import { ReactPlugin } from "@stagewise-plugins/react";
import "./App.css";
import { useState } from "react";

const queryClient = new QueryClient();

function App() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [isMovieView, setIsMovieView] = useState(false);

  const handleTranscriptionChange = (transcription: any) => {
    setIsMovieView(!!transcription);
  };

  return (
    <QueryClientProvider client={queryClient}>
      <StagewiseToolbar config={{ plugins: [ReactPlugin] }} />
      <div className="min-h-screen bg-gradient-to-br from-orange-50 via-pink-50 to-purple-100">
        {/* Header */}
        <header className="hidden bg-gradient-to-r from-purple-600 to-violet-700 text-white py-2">
          <div className="mx-auto max-w-8xl px-4 sm:px-6 lg:px-8">
            <div className="flex h-12 items-center justify-between">
              {/* Logo & Brand */}
              <div className="flex items-center">
                <div className="flex items-center space-x-2">
                  <svg
                    className="h-6 w-6"
                    viewBox="0 0 24 24"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                  >
                    <path
                      d="M12 15C8.667 15 6 13.5 6 10.5V5.5C6 2.5 8.667 1 12 1C15.333 1 18 2.5 18 5.5V10.5C18 13.5 15.333 15 12 15Z"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                    <path
                      d="M10 18.5C10 19.6 10.9 20.5 12 20.5C13.1 20.5 14 19.6 14 18.5V17.5"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                    <path
                      d="M3 10.5V9.5C3 7.84 4.34 6.5 6 6.5"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                    <path
                      d="M21 10.5V9.5C21 7.84 19.66 6.5 18 6.5"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                    <path
                      d="M6 10.5C6 10.5 9 12.5 12 12.5C15 12.5 18 10.5 18 10.5"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                    <path
                      d="M8 23C9.1 23 10 22.1 10 21V20C10 18.9 9.1 18 8 18C6.9 18 6 18.9 6 20V21C6 22.1 6.9 23 8 23Z"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                    <path
                      d="M16 23C17.1 23 18 22.1 18 21V20C18 18.9 17.1 18 16 18C14.9 18 14 18.9 14 20V21C14 22.1 14.9 23 16 23Z"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                  <span className="text-xl font-bold">VoiceScribe</span>
                </div>
              </div>

              {/* Center Navigation */}
              <nav className="hidden md:flex space-x-8">
                <a
                  href="#"
                  className="text-gray-900 hover:text-purple-100 px-3 py-2 font-medium"
                >
                  Home
                </a>
                <a
                  href="#"
                  className="text-gray-900 hover:text-purple-100 px-3 py-2 font-medium"
                >
                  Features
                </a>
                <a
                  href="#"
                  className="text-gray-900 hover:text-purple-100 px-3 py-2 font-medium"
                >
                  Pricing
                </a>
                <a
                  href="#"
                  className="text-gray-900 hover:text-purple-100 px-3 py-2 font-medium"
                >
                  Support
                </a>
              </nav>

              {/* User & Menu */}
              <div className="flex items-center space-x-4">
                <button className="hidden md:flex items-center space-x-1 bg-purple-400 bg-opacity-20 hover:bg-opacity-30 px-3 py-1 rounded-full text-sm">
                  <span>Start Free Trial</span>
                  <svg
                    className="w-4 h-4"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M5 12h14M12 5l7 7-7 7" />
                  </svg>
                </button>
                <div className="flex items-center justify-center h-8 w-8 rounded-full bg-purple-400 bg-opacity-20">
                  <svg
                    className="w-4 h-4"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                    <circle cx="12" cy="7" r="4"></circle>
                  </svg>
                </div>
                <button
                  onClick={() => setMenuOpen(!menuOpen)}
                  className="md:hidden rounded-md p-2 hover:bg-purple-400 hover:bg-opacity-20 focus:outline-none"
                >
                  <svg
                    className="h-6 w-6"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                      d={
                        menuOpen
                          ? "M6 18L18 6M6 6l12 12"
                          : "M4 6h16M4 12h16M4 18h16"
                      }
                    />
                  </svg>
                </button>
              </div>
            </div>
          </div>

          {/* Mobile Menu */}
          {menuOpen && (
            <div className="md:hidden">
              <div className="space-y-0.5 px-2 pt-1 pb-2">
                <a
                  href="#"
                  className="text-gray-900 hover:bg-purple-400 hover:bg-opacity-20 block px-3 py-1 rounded-md text-sm"
                >
                  Home
                </a>
                <a
                  href="#"
                  className="text-gray-900 hover:bg-purple-400 hover:bg-opacity-20 block px-3 py-1 rounded-md text-sm"
                >
                  Features
                </a>
                <a
                  href="#"
                  className="text-gray-900 hover:bg-purple-400 hover:bg-opacity-20 block px-3 py-1 rounded-md text-sm"
                >
                  Pricing
                </a>
                <a
                  href="#"
                  className="text-gray-900 hover:bg-purple-400 hover:bg-opacity-20 block px-3 py-1 rounded-md text-sm"
                >
                  Support
                </a>
              </div>
            </div>
          )}
        </header>

        {/* Only show hero and features if not in movie view */}
        {!isMovieView && (
          <>
            <div className="relative mx-auto max-w-8xl px-4 sm:px-6 lg:px-8 pt-4 pb-6">
              <div className="md:flex md:items-center md:justify-between">
                <div className="md:w-1/2 mb-4 md:mb-0">
                  <h1 className="text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl md:text-5xl">
                    <span className="block">Instant Audio to Text</span>
                    <span className="block bg-gradient-to-r from-purple-600 to-violet-700 bg-clip-text text-transparent">
                      Powered by AI
                    </span>
                  </h1>
                  <p className="mt-2 max-w-md text-base text-gray-500">
                    Transform any audio or video into accurate transcripts with
                    timestamps, translations, and search capabilities.
                  </p>
                  <div className="mt-4">
                    <div className="rounded-xl shadow-lg inline-flex">
                      <a
                        href="#upload"
                        className="flex items-center justify-center px-6 py-3 border border-transparent text-sm font-semibold rounded-xl text-gray-900 bg-gradient-to-r from-purple-500 to-violet-600 hover:from-purple-600 hover:to-violet-700 shadow-lg hover:shadow-xl transition-all duration-200 hover:scale-105"
                      >
                        <span className="text-gray-900 font-semibold">
                          Get Started
                        </span>
                      </a>
                    </div>
                    <div className="inline-flex ml-3">
                      <a
                        href="#"
                        className="flex items-center justify-center px-6 py-3 border border-gray-300 text-sm font-semibold rounded-xl text-gray-900 bg-white hover:bg-gray-50 transition-all duration-200 hover:scale-105 shadow-md hover:shadow-lg"
                      >
                        <span className="text-gray-900 font-semibold">
                          Watch Demo
                        </span>
                      </a>
                    </div>
                  </div>
                </div>
                <div className="md:w-1/2 relative">
                  <div className="w-full flex justify-center">
                    <img
                      className="h-40 sm:h-48 md:h-56 lg:h-64"
                      src="https://img.freepik.com/free-vector/voice-message-concept-illustration_114360-4233.jpg"
                      alt="Audio to Text Illustration"
                    />
                  </div>
                </div>
              </div>
            </div>
            {/* Features Brief */}
            <div className="bg-gradient-to-r from-pink-50 to-purple-100 py-6">
              <div className="mx-auto max-w-8xl px-4 sm:px-6 lg:px-8">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  <div className="bg-white p-4 rounded-xl shadow-sm flex items-start space-x-3">
                    <div className="shrink-0 flex items-center justify-center h-10 w-10 rounded-md bg-gradient-to-r from-purple-500 to-violet-600 text-gray-900">
                      <svg
                        className="h-5 w-5"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth="2"
                          d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
                        />
                      </svg>
                    </div>
                    <div>
                      <h3 className="text-base font-medium text-gray-900">
                        Precise Timestamps
                      </h3>
                      <p className="mt-1 text-xs text-gray-500">
                        Every word precisely timed for perfect subtitle
                        synchronization.
                      </p>
                    </div>
                  </div>
                  <div className="bg-white p-4 rounded-xl shadow-sm flex items-start space-x-3">
                    <div className="shrink-0 flex items-center justify-center h-10 w-10 rounded-md bg-gradient-to-r from-orange-400 to-rose-500 text-gray-900">
                      <svg
                        className="h-5 w-5"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth="2"
                          d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129"
                        />
                      </svg>
                    </div>
                    <div>
                      <h3 className="text-base font-medium text-gray-900">
                        Multi-language Support
                      </h3>
                      <p className="mt-1 text-xs text-gray-500">
                        Automatic language detection with translation
                        capabilities.
                      </p>
                    </div>
                  </div>
                  <div className="bg-white p-4 rounded-xl shadow-sm flex items-start space-x-3">
                    <div className="shrink-0 flex items-center justify-center h-10 w-10 rounded-md bg-gradient-to-r from-rose-400 to-pink-500 text-gray-900">
                      <svg
                        className="h-5 w-5"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth="2"
                          d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                        />
                      </svg>
                    </div>
                    <div>
                      <h3 className="text-base font-medium text-gray-900">
                        Smart Search
                      </h3>
                      <p className="mt-1 text-xs text-gray-500">
                        Find exactly what you need with powerful semantic
                        search.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </>
        )}

        {/* Upload Area */}
        <div id="upload" className="py-4">
          <div className="mx-auto max-w-8xl px-4 sm:px-6 lg:px-8">
            <TranscriptionUpload
              onTranscriptionChange={handleTranscriptionChange}
            />
          </div>
        </div>

        {/* Footer */}
        {false && (
          <footer className="bg-gray-800 text-white">
            <div className="mx-auto max-w-8xl px-4 sm:px-6 lg:px-8 py-12">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
                <div>
                  <h3 className="text-sm font-semibold uppercase tracking-wider">
                    Product
                  </h3>
                  <ul className="mt-4 space-y-2">
                    <li>
                      <a href="#" className="text-gray-300 hover:text-white">
                        Features
                      </a>
                    </li>
                    <li>
                      <a href="#" className="text-gray-300 hover:text-white">
                        Pricing
                      </a>
                    </li>
                    <li>
                      <a href="#" className="text-gray-300 hover:text-white">
                        API
                      </a>
                    </li>
                  </ul>
                </div>

                <div>
                  <h3 className="text-sm font-semibold uppercase tracking-wider">
                    Resources
                  </h3>
                  <ul className="mt-4 space-y-2">
                    <li>
                      <a href="#" className="text-gray-300 hover:text-white">
                        Documentation
                      </a>
                    </li>
                    <li>
                      <a href="#" className="text-gray-300 hover:text-white">
                        Guides
                      </a>
                    </li>
                    <li>
                      <a href="#" className="text-gray-300 hover:text-white">
                        Support
                      </a>
                    </li>
                  </ul>
                </div>

                <div>
                  <h3 className="text-sm font-semibold uppercase tracking-wider">
                    Company
                  </h3>
                  <ul className="mt-4 space-y-2">
                    <li>
                      <a href="#" className="text-gray-300 hover:text-white">
                        About
                      </a>
                    </li>
                    <li>
                      <a href="#" className="text-gray-300 hover:text-white">
                        Blog
                      </a>
                    </li>
                    <li>
                      <a href="#" className="text-gray-300 hover:text-white">
                        Contact
                      </a>
                    </li>
                  </ul>
                </div>

                <div>
                  <h3 className="text-sm font-semibold uppercase tracking-wider">
                    Legal
                  </h3>
                  <ul className="mt-4 space-y-2">
                    <li>
                      <a href="#" className="text-gray-300 hover:text-white">
                        Privacy
                      </a>
                    </li>
                    <li>
                      <a href="#" className="text-gray-300 hover:text-white">
                        Terms
                      </a>
                    </li>
                  </ul>
                </div>
              </div>
              <div className="mt-12 border-t border-gray-700 pt-8">
                <p className="text-sm text-gray-400">
                  © 2023 VoiceScribe. All rights reserved.
                </p>
              </div>
            </div>
          </footer>
        )}
      </div>
    </QueryClientProvider>
  );
}

export default App;

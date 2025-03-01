import { FFmpeg } from '@ffmpeg/ffmpeg';
import { toBlobURL } from '@ffmpeg/util';

let ffmpeg: FFmpeg | null = null;
let isLoading = false;

export const initFFmpeg = async () => {
  if (ffmpeg) return ffmpeg;
  if (isLoading) {
    // Wait for the existing initialization to complete
    while (isLoading) {
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    return ffmpeg;
  }

  try {
    isLoading = true;
    ffmpeg = new FFmpeg();
    
    // Load FFmpeg
    const baseURL = 'https://unpkg.com/@ffmpeg/core@0.12.6/dist/umd';
    await ffmpeg.load({
      coreURL: await toBlobURL(`${baseURL}/ffmpeg-core.js`, 'text/javascript'),
      wasmURL: await toBlobURL(`${baseURL}/ffmpeg-core.wasm`, 'application/wasm'),
    });

    return ffmpeg;
  } catch (error) {
    console.error('Failed to initialize FFmpeg:', error);
    ffmpeg = null;
    throw new Error('Failed to initialize FFmpeg. Please check your internet connection and try again.');
  } finally {
    isLoading = false;
  }
};

export const extractAudio = async (
  videoFile: File,
  onProgress?: (progress: number) => void
): Promise<Blob> => {
  const instance = await initFFmpeg();
  if (!instance) {
    throw new Error('FFmpeg is not initialized');
  }
  
  try {
    // Convert File to ArrayBuffer
    const videoData = await videoFile.arrayBuffer();
    
    // Write video file to FFmpeg filesystem
    await instance.writeFile('input.mp4', new Uint8Array(videoData));
    
    // Set up progress handler
    if (onProgress) {
      instance.on('progress', ({ progress }) => {
        onProgress(Math.round(progress * 100));
      });
    }
    
    // Extract audio with reasonable quality (128k bitrate)
    await instance.exec([
      '-i', 'input.mp4',
      '-vn',                // Skip video
      '-acodec', 'mp3',    // Output format
      '-ab', '128k',       // Bitrate
      '-ar', '44100',      // Sample rate
      'output.mp3'
    ]);
    
    // Read the output file
    const audioData = await instance.readFile('output.mp3');
    
    // Clean up
    await instance.deleteFile('input.mp4');
    await instance.deleteFile('output.mp3');
    
    // Convert to Blob
    return new Blob([audioData], { type: 'audio/mp3' });
  } catch (error) {
    console.error('Failed to extract audio:', error);
    throw new Error('Failed to extract audio from video. Please try again.');
  }
};

export const getAudioDuration = async (audioBlob: Blob): Promise<number> => {
  return new Promise((resolve, reject) => {
    const audio = new Audio();
    audio.src = URL.createObjectURL(audioBlob);
    
    audio.addEventListener('loadedmetadata', () => {
      const duration = audio.duration;
      URL.revokeObjectURL(audio.src);
      resolve(duration);
    });

    audio.addEventListener('error', () => {
      URL.revokeObjectURL(audio.src);
      reject(new Error('Failed to load audio file'));
    });
  });
}; 
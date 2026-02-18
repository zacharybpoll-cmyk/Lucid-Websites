"""
Audio capture using sounddevice
Continuously captures microphone input in background thread
"""
import sounddevice as sd
import numpy as np
from typing import Callable, Optional
import queue
import app_config as config

class AudioCapture:
    def __init__(self,
                 sample_rate: int = config.SAMPLE_RATE,
                 channels: int = config.CHANNELS,
                 chunk_duration_ms: int = config.CHUNK_DURATION_MS,
                 on_audio_callback: Optional[Callable] = None):
        """
        Args:
            sample_rate: Audio sample rate (Hz)
            channels: Number of audio channels (1=mono)
            chunk_duration_ms: Duration of each audio chunk in milliseconds
            on_audio_callback: Function to call with each audio chunk
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_duration_ms = chunk_duration_ms
        self.chunk_size = int(sample_rate * chunk_duration_ms / 1000)
        self.on_audio_callback = on_audio_callback

        self.stream = None
        self.is_running = False
        self.audio_queue = queue.Queue()

    def _audio_callback(self, indata, frames, time, status):
        """
        Callback for sounddevice InputStream
        Runs in separate thread
        """
        if status:
            print(f"[AudioCapture] Status: {status}")

        # Copy audio data (indata is a view, needs to be copied)
        audio_chunk = indata.copy().flatten()

        # Put in queue for processing
        if self.on_audio_callback:
            try:
                self.on_audio_callback(audio_chunk)
            except Exception as e:
                print(f"[AudioCapture] Error in callback: {e}")

    def start(self):
        """Start audio capture"""
        if self.is_running:
            print("[AudioCapture] Already running")
            return

        try:
            print(f"[AudioCapture] Starting audio capture at {self.sample_rate}Hz, {self.channels} channel(s)")
            print(f"[AudioCapture] Chunk size: {self.chunk_size} samples ({self.chunk_duration_ms}ms)")

            # List available devices
            devices = sd.query_devices()
            default_input = sd.query_devices(kind='input')
            print(f"[AudioCapture] Using input device: {default_input['name']}")

            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=self._audio_callback,
                blocksize=self.chunk_size,
                dtype=np.float32
            )

            self.stream.start()
            self.is_running = True
            print("[AudioCapture] Audio capture started successfully")

        except Exception as e:
            print(f"[AudioCapture] Error starting audio capture: {e}")
            raise

    def stop(self):
        """Stop audio capture"""
        if not self.is_running:
            return

        print("[AudioCapture] Stopping audio capture")
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        self.is_running = False
        print("[AudioCapture] Audio capture stopped")

    def pause(self):
        """Pause audio capture"""
        if self.stream and self.is_running:
            self.stream.stop()
            self.is_running = False
            print("[AudioCapture] Audio capture paused")

    def resume(self):
        """Resume audio capture"""
        if self.stream and not self.is_running:
            self.stream.start()
            self.is_running = True
            print("[AudioCapture] Audio capture resumed")

    def get_device_info(self):
        """Get information about audio devices"""
        return {
            'devices': sd.query_devices(),
            'default_input': sd.query_devices(kind='input'),
            'default_output': sd.query_devices(kind='output')
        }

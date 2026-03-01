"""
Audio capture using sounddevice
Continuously captures microphone input in background thread
Includes device monitoring with automatic disconnect detection and reconnection
"""
import logging
import sounddevice as sd
import numpy as np
from typing import Callable, Optional
import queue
import threading
import app_config as config

logger = logging.getLogger('attune.audio')

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

        # Device monitor for disconnect detection/recovery
        self._device_monitor_thread = None
        self._monitor_stop = threading.Event()
        self._on_disconnect_callback = None
        self._on_reconnect_callback = None

    def set_disconnect_callback(self, on_disconnect=None, on_reconnect=None):
        """Set callbacks for mic disconnect/reconnect events."""
        self._on_disconnect_callback = on_disconnect
        self._on_reconnect_callback = on_reconnect

    def _start_device_monitor(self):
        """Start background thread to monitor audio device availability."""
        self._monitor_stop.clear()
        self._device_monitor_thread = threading.Thread(
            target=self._monitor_device, daemon=True)
        self._device_monitor_thread.start()

    def _monitor_device(self):
        """Poll for audio device availability every 5 seconds."""
        while not self._monitor_stop.is_set():
            self._monitor_stop.wait(5.0)
            if self._monitor_stop.is_set():
                break
            if self.is_running:
                try:
                    sd.query_devices(kind='input')
                except Exception as e:
                    logger.error("Input device lost: %s", e)
                    self._handle_disconnect()

    def _handle_disconnect(self):
        """Handle mic disconnect with exponential backoff reconnection."""
        self.is_running = False
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception as e:
                logger.debug("Error stopping stream during disconnect: %s", e)
            self.stream = None

        if self._on_disconnect_callback:
            try:
                self._on_disconnect_callback()
            except Exception as e:
                logger.debug("Disconnect callback error: %s", e)

        # Attempt reconnection with exponential backoff: 2, 4, 8, 16, 32 seconds
        for attempt in range(5):
            delay = 2 ** (attempt + 1)
            logger.info(f"Reconnection attempt {attempt + 1}/5 in {delay}s...")
            self._monitor_stop.wait(delay)
            if self._monitor_stop.is_set():
                return

            try:
                sd.query_devices(kind='input')
                self.start()
                logger.info("Reconnected successfully!")
                if self._on_reconnect_callback:
                    try:
                        self._on_reconnect_callback()
                    except Exception as e2:
                        logger.debug("Reconnect callback error: %s", e2)
                return
            except Exception as e:
                logger.warning(f"Reconnection attempt {attempt + 1} failed: {e}")

        logger.error("All reconnection attempts failed")
        # Notify orchestrator of permanent disconnect (user needs feedback)
        if self._on_disconnect_callback:
            try:
                self._on_disconnect_callback(permanent=True)
            except TypeError:
                # Callback doesn't accept permanent kwarg — call without
                try:
                    self._on_disconnect_callback()
                except Exception as e2:
                    logger.debug("Disconnect callback fallback error: %s", e2)
            except Exception as e3:
                logger.debug("Permanent disconnect callback error: %s", e3)

    def _audio_callback(self, indata, frames, time, status):
        """
        Callback for sounddevice InputStream.
        Runs in the audio thread — must never raise.

        TS-010: Entire body wrapped in try/except to prevent crashes
        in the sounddevice audio thread (which would kill the stream).
        """
        try:
            if status:
                logger.warning(f"Status: {status}")

            # Copy audio data (indata is a view, needs to be copied)
            audio_chunk = indata.copy().flatten()

            # Put in queue for processing
            if self.on_audio_callback:
                self.on_audio_callback(audio_chunk)
        except Exception as e:
            logger.error(f"Audio callback error: {e}")

    def start(self):
        """Start audio capture"""
        if self.is_running:
            logger.warning("Already running")
            return

        try:
            logger.info(f"Starting audio capture at {self.sample_rate}Hz, {self.channels} channel(s)")
            logger.info(f"Chunk size: {self.chunk_size} samples ({self.chunk_duration_ms}ms)")

            # List available devices
            devices = sd.query_devices()
            default_input = sd.query_devices(kind='input')
            logger.info(f"Using input device: {default_input['name']}")

            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=self._audio_callback,
                blocksize=self.chunk_size,
                dtype=np.float32
            )

            self.stream.start()
            self.is_running = True
            logger.info("Audio capture started successfully")

            # Start device monitor for disconnect detection
            self._start_device_monitor()

        except Exception as e:
            logger.error(f"Error starting audio capture: {e}")
            raise

    def stop(self):
        """Stop audio capture.
        TS-003: Signals monitor stop and joins thread with timeout."""
        if not self.is_running:
            return

        logger.info("Stopping audio capture")

        # Stop device monitor thread
        self._monitor_stop.set()
        if self._device_monitor_thread and self._device_monitor_thread.is_alive():
            self._device_monitor_thread.join(timeout=5)
            if self._device_monitor_thread.is_alive():
                logger.warning("Device monitor thread did not stop within timeout")

        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        self.is_running = False
        logger.info("Audio capture stopped")

    def pause(self):
        """Pause audio capture"""
        if self.stream and self.is_running:
            self.stream.stop()
            self.is_running = False
            logger.info("Audio capture paused")

    def resume(self):
        """Resume audio capture"""
        if self.stream and not self.is_running:
            self.stream.start()
            self.is_running = True
            logger.info("Audio capture resumed")

    def get_device_info(self):
        """Get information about audio devices"""
        return {
            'devices': sd.query_devices(),
            'default_input': sd.query_devices(kind='input'),
            'default_output': sd.query_devices(kind='output')
        }

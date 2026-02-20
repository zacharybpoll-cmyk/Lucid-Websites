/**
 * AudioWorklet processor for PCM capture during voice profile recording.
 * Replaces deprecated ScriptProcessorNode for better performance and
 * standards compliance.
 *
 * Runs on the audio rendering thread — receives raw Float32 samples,
 * converts to Int16 PCM, and posts them back to the main thread.
 */
class PcmCaptureProcessor extends AudioWorkletProcessor {
  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (input && input.length > 0) {
      const channelData = input[0];
      const int16 = new Int16Array(channelData.length);
      for (let i = 0; i < channelData.length; i++) {
        const s = Math.max(-1, Math.min(1, channelData[i]));
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }
      // Transfer the buffer to the main thread (zero-copy)
      this.port.postMessage({ pcm: int16 }, [int16.buffer]);
    }
    return true; // Keep processor alive
  }
}

registerProcessor('pcm-capture-processor', PcmCaptureProcessor);

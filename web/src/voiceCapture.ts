/* Browser-only capture: mono PCM WAV at 16 kHz. Audio is held in memory only. */
export type VoiceCapture = { finish: () => Promise<Blob>; cancel: () => void };
export async function startVoiceCapture(stream: MediaStream): Promise<VoiceCapture> {
  let context: AudioContext | null = null;
  let source: MediaStreamAudioSourceNode | null = null;
  let processor: AudioWorkletNode | null = null;
  let muted: GainNode | null = null;
  let closed = false;
  const samples: Float32Array[] = [];
  let captured = 0;
  const workletUrl = URL.createObjectURL(new Blob([`
    class MonoRecorder extends AudioWorkletProcessor {
      process(inputs) {
        if (inputs[0]?.[0]) this.port.postMessage(inputs[0][0].slice());
        return true;
      }
    }
    registerProcessor('mono-recorder', MonoRecorder);
  `], { type: 'application/javascript' }));
  function cleanup() {
    closed = true;
    stream.getTracks().forEach((track) => track.stop());
    if (processor) { processor.port.onmessage = null; processor.disconnect(); }
    source?.disconnect(); muted?.disconnect();
    void context?.close();
  }
  try {
    context = new AudioContext();
    await context.audioWorklet.addModule(workletUrl);
    if (!stream.active) throw new Error('Recording was cancelled.');
    source = context.createMediaStreamSource(stream);
    processor = new AudioWorkletNode(context, 'mono-recorder', { channelCount: 1, channelCountMode: 'explicit' });
    processor.port.onmessage = (event: MessageEvent<Float32Array>) => {
      if (!closed && captured < context!.sampleRate * 60) { samples.push(event.data); captured += event.data.length; }
    };
    muted = context.createGain(); muted.gain.value = 0;
    source.connect(processor); processor.connect(muted); muted.connect(context.destination);
    await context.resume();
    const sampleRate = context.sampleRate;
    return {
      cancel: () => { cleanup(); samples.length = 0; },
      finish: async () => {
        cleanup();
        const count = samples.reduce((sum, sample) => sum + sample.length, 0);
        if (count < sampleRate / 10) { samples.length = 0; throw new Error('Recording was too short. Record at least a moment of speech.'); }
        const joined = new Float32Array(count);
        let offset = 0;
        for (const sample of samples) { joined.set(sample, offset); offset += sample.length; }
        samples.length = 0;
        const rate = 16000;
        const length = Math.min(rate * 60, Math.floor(count * rate / sampleRate));
        const wav = new ArrayBuffer(44 + length * 2);
        const view = new DataView(wav);
        const ascii = (position: number, text: string) => [...text].forEach((character, index) => view.setUint8(position + index, character.charCodeAt(0)));
        ascii(0, 'RIFF'); view.setUint32(4, 36 + length * 2, true); ascii(8, 'WAVE'); ascii(12, 'fmt ');
        view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
        view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
        ascii(36, 'data'); view.setUint32(40, length * 2, true);
        for (let index = 0; index < length; index++) {
          const start = Math.floor(index * sampleRate / rate);
          const end = Math.min(count, Math.max(start + 1, Math.floor((index + 1) * sampleRate / rate)));
          let value = 0;
          for (let part = start; part < end; part++) value += joined[part];
          value = Math.max(-1, Math.min(1, value / (end - start)));
          view.setInt16(44 + index * 2, value < 0 ? value * 32768 : value * 32767, true);
        }
        return new Blob([wav], { type: 'audio/wav' });
      },
    };
  } catch (reason) { cleanup(); throw reason; }
  finally { URL.revokeObjectURL(workletUrl); }
}

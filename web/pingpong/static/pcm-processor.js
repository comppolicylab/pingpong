class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.inputSampleRate = sampleRate;
    this.outputSampleRate = 24000;
    this.ratio = this.inputSampleRate / this.outputSampleRate;
    this.buffer = [];
    this.TARGET_CHUNK_SIZE = 2400; // 100ms of audio at 24kHz
  }

  downsampleBuffer(buffer) {
    const outLength = Math.floor(buffer.length / this.ratio);
    const result = new Int16Array(outLength);
    let offsetResult = 0;
    let offsetBuffer = 0;

    while (offsetResult < result.length) {
      const nextOffsetBuffer = Math.floor((offsetResult + 1) * this.ratio);
      let sum = 0, count = 0;
      for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
        sum += buffer[i];
        count++;
      }
      const avg = sum / count;
      const intSample = Math.max(-1, Math.min(1, avg));
      result[offsetResult] = intSample < 0 ? intSample * 0x8000 : intSample * 0x7FFF;
      offsetResult++;
      offsetBuffer = nextOffsetBuffer;
    }

    return result;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;

    const monoInput = input[0];
    const downsampled = this.downsampleBuffer(monoInput);

    this.buffer.push(...downsampled);

    if (this.buffer.length >= this.TARGET_CHUNK_SIZE) {
      const chunk = this.buffer.slice(0, this.TARGET_CHUNK_SIZE);
      this.buffer = this.buffer.slice(this.TARGET_CHUNK_SIZE);

      const pcmChunk = new Int16Array(chunk);
      this.port.postMessage(pcmChunk.buffer, [pcmChunk.buffer]);
    }

    return true;
  }
}

registerProcessor("pcm-processor", PCMProcessor);
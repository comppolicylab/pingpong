/**
 * Parts of this code are derived from the following copyrighted
 * material, the use of which is hereby acknowledged.
 *
 * OpenAI (openai-realtime-console)
 *
 * MIT License
 *
 * Copyright (c) 2024 OpenAI
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

export const StreamProcessorWorklet = `
class StreamProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.hasStarted = false;
    this.hasInterrupted = false;
    this.outputBuffers = [];
    this.bufferLength = 128;
    this.write = {
      buffer: new Float32Array(this.bufferLength),
      validSampleCount: 0,
      trackId: null,
      eventId: null,
    };
    this.writeOffset = 0;
    this.trackSampleOffsets = {};
    this.currentlyPlayingTrackId = null;
    this.currentlyPlayingEventId = null;
    this.lastStartedEventId = null;
    this.lastEndedEventId = null;
    this.eventStartOffsets = {};
    this.eventEndOffsets = {};
    this.processedEventIds = new Set();
    this.endedEventIds = new Set();
    this.port.onmessage = (event) => {
      if (event.data) {
        const payload = event.data;
        if (payload.event === 'write') {
          const int16Array = payload.buffer;
          const float32Array = new Float32Array(int16Array.length);
          for (let i = 0; i < int16Array.length; i++) {
            float32Array[i] = int16Array[i] / 0x8000; // Convert Int16 to Float32
          }
          this.writeData(float32Array, payload.trackId, payload.eventId);
        } else if (
          payload.event === 'offset' ||
          payload.event === 'interrupt'
        ) {
          const requestId = payload.requestId;
          const trackId = this.currentlyPlayingTrackId;
          const offset = trackId ? this.trackSampleOffsets[trackId] || 0 : 0;
          this.port.postMessage({
            event: 'offset',
            requestId,
            trackId,
            offset,
            eventId: this.currentlyPlayingEventId,
            lastStartedEventId: this.lastStartedEventId,
            lastStartedEventOffset: this.lastStartedEventId
              ? this.eventStartOffsets[this.lastStartedEventId] ?? null
              : null,
            lastEndedEventId: this.lastEndedEventId,
            lastEndedEventOffset: this.lastEndedEventId
              ? this.eventEndOffsets[this.lastEndedEventId] ?? null
              : null,
          });
          if (payload.event === 'interrupt') {
            this.hasInterrupted = true;
          }
        } else {
          throw new Error(\`Unhandled event "\${payload.event}"\`);
        }
      }
    };
  }

  writeData(float32Array, trackId = null, eventId = null) {
    if (
      this.writeOffset > 0 &&
      (this.write.trackId !== trackId || this.write.eventId !== eventId)
    ) {
      this.flushWriteBuffer();
    }
    this.write.trackId = trackId;
    this.write.eventId = eventId;
    let { buffer } = this.write;
    let offset = this.writeOffset;
    for (let i = 0; i < float32Array.length; i++) {
      buffer[offset++] = float32Array[i];
      this.write.validSampleCount++;
      if (offset >= buffer.length) {
        this.outputBuffers.push(this.write);
        this.write = {
          buffer: new Float32Array(this.bufferLength),
          validSampleCount: 0,
          trackId,
          eventId,
        };
        buffer = this.write.buffer;
        offset = 0;
      }
    }
    this.writeOffset = offset;
    return true;
  }

  flushWriteBuffer() {
    if (this.writeOffset === 0) {
      return false;
    }
    this.outputBuffers.push(this.write);
    this.write = {
      buffer: new Float32Array(this.bufferLength),
      validSampleCount: 0,
      trackId: null,
      eventId: null,
    };
    this.writeOffset = 0;
    return true;
  }

  process(inputs, outputs, parameters) {
    const output = outputs[0];
    const outputChannelData = output[0];
    const outputBuffers = this.outputBuffers;
    if (this.hasInterrupted) {
      this.port.postMessage({ event: 'stop' });
      return false;
    } else if (outputBuffers.length) {
      this.hasStarted = true;
      const { buffer, validSampleCount, trackId, eventId } = outputBuffers.shift();
      const startTimestamp = Date.now();
      for (let i = 0; i < outputChannelData.length; i++) {
        outputChannelData[i] = buffer[i] || 0;
      }
      this.currentlyPlayingTrackId = trackId;
      this.currentlyPlayingEventId = eventId;
      if (trackId) {
        this.trackSampleOffsets[trackId] =
          this.trackSampleOffsets[trackId] || 0;
        const startOffset = this.trackSampleOffsets[trackId];
        this.trackSampleOffsets[trackId] += validSampleCount;
        const endOffset = this.trackSampleOffsets[trackId];
        if (
          eventId &&
          !Object.prototype.hasOwnProperty.call(this.eventStartOffsets, eventId)
        ) {
          this.eventStartOffsets[eventId] = startOffset;
        }
        if (eventId) {
          this.eventEndOffsets[eventId] = endOffset;
        }
      }
      if (eventId && !this.processedEventIds.has(eventId)) {
        this.port.postMessage({
            event: 'audio_part_started',
            trackId: trackId,
            eventId: eventId,
            timestamp: startTimestamp,
        });
        this.lastStartedEventId = eventId;
        this.processedEventIds.add(eventId);
      }
      if (
        eventId &&
        !this.endedEventIds.has(eventId) &&
        !outputBuffers.some((queued) => queued.eventId === eventId) &&
        (this.writeOffset === 0 || this.write.eventId !== eventId)
      ) {
        this.port.postMessage({
            event: 'audio_part_ended',
            trackId: trackId,
            eventId: eventId,
            timestamp: Date.now(),
        });
        this.lastEndedEventId = eventId;
        this.endedEventIds.add(eventId);
      }
      return true;
    } else if (this.hasStarted) {
      if (this.flushWriteBuffer()) {
        return true;
      }
      this.port.postMessage({ event: 'stop' });
      return false;
    } else {
      return true;
    }
  }
}

registerProcessor('stream_processor', StreamProcessor);
`;

const script = new Blob([StreamProcessorWorklet], {
	type: 'application/javascript'
});
const src: string = URL.createObjectURL(script);
export const StreamProcessorSrc: string = src;

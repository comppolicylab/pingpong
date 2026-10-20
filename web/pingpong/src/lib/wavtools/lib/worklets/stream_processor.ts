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
    this.processedEventIds = new Set();
    this.endedEventIds = new Set();
    this.stopOnEmptyBuffer = true;
    this.finishWhenDrained = false;
    this.tracks = new Map();
    this.settledTrackIds = new Set();
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
          const eventId = this.currentlyPlayingEventId;
          if (payload.event === 'interrupt') {
            this.hasInterrupted = true;
            for (const [id, track] of this.tracks) {
              this.settleTrack(id, track.played ? 'interrupted' : 'discarded');
            }
            this.outputBuffers = [];
            this.writeOffset = 0;
          }
          // Report the offset after all settlements, so an interrupt receipt
          // also means queued-reply outcomes have reached the main thread.
          this.port.postMessage({
            event: 'offset',
            requestId,
            trackId,
            offset,
            eventId,
          });
        } else if (payload.event === 'configure') {
          if (typeof payload.stopOnEmptyBuffer === 'boolean') {
            this.stopOnEmptyBuffer = payload.stopOnEmptyBuffer;
          }
        } else if (payload.event === 'finish') {
          this.finishWhenDrained = true;
          for (const track of this.tracks.values()) track.generationDone = true;
        } else if (payload.event === 'finish_track') {
          if (!this.hasInterrupted && !this.settledTrackIds.has(payload.trackId)) {
            const track = this.getTrack(payload.trackId);
            track.generationDone = true;
          }
        } else {
          throw new Error(\`Unhandled event "\${payload.event}"\`);
        }
      }
    };
  }

  writeData(float32Array, trackId = null, eventId = null) {
    if (this.hasInterrupted || this.settledTrackIds.has(trackId) || !float32Array.length) {
      return false;
    }
    const track = this.getTrack(trackId);
    if (track.generationDone) return false;
    track.pendingSamples += float32Array.length;
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

  getTrack(trackId) {
    if (!this.tracks.has(trackId)) {
      this.tracks.set(trackId, { pendingSamples: 0, played: false, generationDone: false });
    }
    return this.tracks.get(trackId);
  }

  settleTrack(trackId, outcome) {
    const track = this.tracks.get(trackId);
    if (!track || this.settledTrackIds.has(trackId)) return;
    this.settledTrackIds.add(trackId);
    this.tracks.delete(trackId);
    this.port.postMessage({ event: 'track_settled', trackId, outcome, played: track.played });
    if (this.currentlyPlayingTrackId === trackId) {
      this.currentlyPlayingTrackId = null;
      this.currentlyPlayingEventId = null;
    }
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
    // A preceding render quantum has now advanced. Empty gaps while generation
    // continues are not terminal, even if every received chunk has played.
    for (const [trackId, track] of this.tracks) {
      if (track.generationDone && track.pendingSamples === 0) {
        this.settleTrack(trackId, track.played ? 'completed' : 'discarded');
      }
    }
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
      const track = this.tracks.get(trackId);
      track.pendingSamples -= validSampleCount;
      track.played = track.played || validSampleCount > 0;
      if (trackId) {
        this.trackSampleOffsets[trackId] =
          this.trackSampleOffsets[trackId] || 0;
        this.trackSampleOffsets[trackId] += validSampleCount;
      }
      if (eventId && !this.processedEventIds.has(eventId)) {
        this.port.postMessage({
            event: 'audio_part_started',
            trackId: trackId,
            eventId: eventId,
            timestamp: startTimestamp,
        });
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
        this.endedEventIds.add(eventId);
      }
      return true;
    } else if (this.hasStarted) {
      if (this.flushWriteBuffer()) {
        return true;
      }
      if (!this.stopOnEmptyBuffer && !this.finishWhenDrained) {
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

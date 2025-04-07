/**
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

/**
 * Raw wav audio file contents
 * @typedef {Object} WavPackerAudioType
 * @property {Blob} blob
 * @property {string} url
 * @property {number} channelCount
 * @property {number} sampleRate
 * @property {number} duration
 */

export interface WavPackerAudioType {
  blob: Blob;
  url: string;
  channelCount: number;
  sampleRate: number;
  duration: number;
}

export interface AudioData {
  bitsPerSample: number;
  channels: Float32Array[];
  data: Int16Array;
}

/**
 * Utility class for assembling PCM16 "audio/wav" data
 * @class
 */
export class WavPacker {
  /**
   * Converts Float32Array of amplitude data to ArrayBuffer in Int16Array format
   * @param {Float32Array} float32Array
   * @returns {ArrayBuffer}
   */
  static floatTo16BitPCM(float32Array: Float32Array): ArrayBuffer {
    const buffer = new ArrayBuffer(float32Array.length * 2);
    const view = new DataView(buffer);
    let offset = 0;
    for (let i = 0; i < float32Array.length; i++, offset += 2) {
      const s = Math.max(-1, Math.min(1, float32Array[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return buffer;
  }

  /**
   * Concatenates two ArrayBuffers
   * @param {ArrayBuffer} leftBuffer
   * @param {ArrayBuffer} rightBuffer
   * @returns {ArrayBuffer}
   */
  static mergeBuffers(leftBuffer: ArrayBuffer, rightBuffer: ArrayBuffer): ArrayBuffer {
    const tmpArray = new Uint8Array(leftBuffer.byteLength + rightBuffer.byteLength);
    tmpArray.set(new Uint8Array(leftBuffer), 0);
    tmpArray.set(new Uint8Array(rightBuffer), leftBuffer.byteLength);
    return tmpArray.buffer;
  }

  /**
   * Packs data into an Int16 format
   * @private
   * @param {number} size 0 = 1x Int16, 1 = 2x Int16
   * @param {number} arg value to pack
   * @returns {Uint8Array}
   */
  _packData(size: number, arg: number): Uint8Array {
    return [new Uint8Array([arg, arg >> 8]), new Uint8Array([arg, arg >> 8, arg >> 16, arg >> 24])][
      size
    ];
  }

  /**
   * Packs audio into "audio/wav" Blob
   * @param {number} sampleRate
   * @param {{bitsPerSample: number, channels: Array<Float32Array>, data: Int16Array}} audio
   * @returns {WavPackerAudioType}
   */
  pack(
    sampleRate: number,
    audio: { bitsPerSample: number; channels: Array<Float32Array>; data: Int16Array }
  ): WavPackerAudioType {
    if (!audio?.bitsPerSample) {
      throw new Error(`Missing "bitsPerSample"`);
    } else if (!audio?.channels) {
      throw new Error(`Missing "channels"`);
    } else if (!audio?.data) {
      throw new Error(`Missing "data"`);
    }
    const { bitsPerSample, channels, data } = audio;
    const output = [
      // Header
      'RIFF',
      this._packData(1, 4 + (8 + 24) /* chunk 1 length */ + (8 + 8) /* chunk 2 length */), // Length
      'WAVE',
      // chunk 1
      'fmt ', // Sub-chunk identifier
      this._packData(1, 16), // Chunk length
      this._packData(0, 1), // Audio format (1 is linear quantization)
      this._packData(0, channels.length),
      this._packData(1, sampleRate),
      this._packData(1, (sampleRate * channels.length * bitsPerSample) / 8), // Byte rate
      this._packData(0, (channels.length * bitsPerSample) / 8),
      this._packData(0, bitsPerSample),
      // chunk 2
      'data', // Sub-chunk identifier
      this._packData(1, (channels[0].length * channels.length * bitsPerSample) / 8), // Chunk length
      data
    ];
    const blob = new Blob(output, { type: 'audio/mpeg' });
    const url = URL.createObjectURL(blob);
    return {
      blob,
      url,
      channelCount: channels.length,
      sampleRate,
      duration: data.byteLength / (channels.length * sampleRate * 2)
    };
  }
}

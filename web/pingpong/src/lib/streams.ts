/**
 * A stream that parses chunks as JSON objects.
 */
export class JSONStream extends TransformStream<string, object> {
  constructor() {
    super({
      transform(chunk, controller) {
        try {
          controller.enqueue(JSON.parse(chunk));
        } catch (e) {
          controller.error(e);
        }
      }
    });
  }
}

/**
 * A stream that emits lines of text in chunks as they are received.
 */
export class TextLineStream extends TransformStream<string, string> {
  constructor() {
    let buffer = '';

    super({
      transform(chunk, controller) {
        // Add characters to the buffer, emitting at each newline
        for (const char of chunk) {
          if (char === '\n') {
            controller.enqueue(buffer);
            buffer = '';
          } else {
            buffer += char;
          }
        }
      },
      flush(controller) {
        // If there's anything left in the buffer, emit it
        if (buffer.length > 0) {
          controller.enqueue(buffer);
          buffer = '';
        }
      }
    });
  }
}

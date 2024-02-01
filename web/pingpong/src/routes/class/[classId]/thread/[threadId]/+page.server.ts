import * as api from '$lib/api';
import { forwardRequest } from '$lib/proxy';
import {invalid} from "$lib/validate";
import type {Actions} from "./$types";

export const actions: Actions = {

    /**
     * Add a new message to a thread.
     */
    newMessage: async(event) => {
      return await forwardRequest((f, d) => {
        const classId = parseInt(event.params.classId, 10);
        const threadId = parseInt(event.params.threadId, 10);
        const message = d['message'];
        if (!message) {
          throw invalid("message", "Message is required");
        }
        return api.postMessage(f, classId, threadId, {message});
      }, event);
    },

};

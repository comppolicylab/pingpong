import {fail} from "@sveltejs/kit";
import type {RequestEvent} from "@sveltejs/kit";
import type {Fetcher, BaseData, BaseResponse} from "./api";

export interface ForwardRequestOptions {
  checkboxes?: string[];
}

type FormBody = [string, any][];

type Thunk<E extends RequestEvent> = (f: Fetcher, r: Record<string, any>, event: E) => Promise<BaseData & BaseResponse>;

export const handler = <E extends RequestEvent, T extends Thunk<E>>(thunk: T, opts?: ForwardRequestOptions) => {
  return async (event: E) => {
    return await forwardRequest(thunk, event, opts);
  };
};

export const forwardRequest = async <E extends RequestEvent, T extends Thunk<E>>(thunk: T, event: E, opts?: ForwardRequestOptions) => {
    const formData = await event.request.formData();
    const body = Array.from(formData.entries()) as FormBody;

    const booleanFields = opts?.checkboxes || [];

    const reqData = body.reduce((agg, cur) => {
      const key = cur[0];
      const val = booleanFields.includes(key) ? cur[1] === "on" : cur[1];
      if (agg.hasOwnProperty(key)) {
        if (Array.isArray(agg[key])) {
          (agg[key] as any[]).push(val);
        } else {
          agg[key] = [agg[key], val];
        }
      } else {
        agg[key] = val;
      }
      return agg;
    }, {} as Record<string, any>);

    // Ensure all boolean fields are set
    for (const key of booleanFields) {
      if (!reqData[key]) {
        reqData[key] = false;
      }
    }

    try {
      const result = await thunk(event.fetch, reqData, event)
      if (result.$status >= 400) {
        throw result;
      }
      return result;
    } catch (e) {
      if (!e) {
        return fail(500, {
          $status: 500,
          success: false,
          detail: "Unknown error",
        });
      } else if (e.hasOwnProperty("$status")) {
        const detail = (e as any).detail;
        const field = Array.isArray(detail) ? detail[0].loc.join(".") : (e as any).field || undefined;
        const msg = Array.isArray(detail) ? detail[0].msg : detail || "Unknown error";
        return fail((e as any).$status, {
          $status: (e as any).$status,
          success: false,
          field,
          detail: msg,
        });
      } else if (e instanceof Error) {
        return fail(500, {
          $status: 500,
          success: false,
          detail: e.message,
        });
      } else {
        return fail(500, {
          $status: 500,
          success: false,
          detail: JSON.stringify(e),
        });
      }
    }
}

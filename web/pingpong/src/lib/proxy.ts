import {fail} from "@sveltejs/kit";
import type {RequestEvent} from "@sveltejs/kit";
import type {Fetcher, BaseData, BaseResponse} from "./api";

export interface ForwardRequestOptions {
  checkboxes?: string[];
}

type FormBody = [string, any][];

export const forwardRequest = async <T extends ((f: Fetcher, r: Record<string, any>) => Promise<BaseData & BaseResponse>)>(thunk: T, { fetch, request}: RequestEvent, opts?: ForwardRequestOptions) => {
    const formData = await request.formData();
    const body = Array.from(formData.entries()) as FormBody;

    const booleanFields = opts?.checkboxes || [];

    const reqData = body.reduce((agg, cur) => {
      if (booleanFields.includes(cur[0])) {
        agg[cur[0]] = cur[1] === "on";
      } else {
        agg[cur[0]] = cur[1];
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
      const result = await thunk(fetch, reqData)
      return result;
    } catch (e) {
      if (!e) {
        return fail(500, {
          $status: 500,
          success: false,
          detail: "Unknown error",
        });
      } else if (e.hasOwnProperty("$status")) {
        return fail((e as any).$status, {
          $status: (e as any).$status,
          success: false,
          field: (e as any).field || undefined,
          detail: (e as any).detail || "Unknown error",
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

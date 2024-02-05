import { fail } from '@sveltejs/kit';
import type { RequestEvent } from '@sveltejs/kit';
import type { Fetcher, BaseData, BaseResponse } from './api';

export interface ForwardRequestOptions {
  checkboxes?: string[];
  lists?: string[];
}

type FormBody = [string, string][];

type Thunk<E extends RequestEvent, D extends Record<string, unknown>> = (
  f: Fetcher,
  r: D,
  event: E
) => Promise<BaseData & BaseResponse>;

/**
 * Server-side request handler.
 */
export const handler = <E extends RequestEvent, D extends Record<string, unknown>>(
  thunk: Thunk<E, D>,
  opts?: ForwardRequestOptions
) => {
  return async (event: E) => {
    return await forwardRequest(thunk, event, opts);
  };
};

export const forwardRequest = async <E extends RequestEvent, D extends Record<string, unknown>>(
  thunk: Thunk<E, D>,
  event: E,
  opts?: ForwardRequestOptions
) => {
  const formData = await event.request.formData();
  const body = Array.from(formData.entries()) as FormBody;

  const booleanFields = opts?.checkboxes || [];
  const lists = opts?.lists || [];

  const reqData = body.reduce(
    (agg, cur) => {
      const key = cur[0];
      const val = booleanFields.includes(key) ? cur[1] === 'on' : cur[1];
      if (lists.includes(key)) {
        if (Object.hasOwn(agg, key)) {
          (agg[key] as unknown[]).push(val);
        } else {
          agg[key] = [val];
        }
      } else {
        agg[key] = val;
      }
      return agg;
    },
    {} as Record<string, unknown>
  );

  // Ensure all boolean fields are set
  for (const key of booleanFields) {
    if (!reqData[key]) {
      reqData[key] = false;
    }
  }

  try {
    const result = await thunk(event.fetch, reqData as D, event);
    if (result.$status >= 400) {
      throw result;
    }
    return result;
  } catch (e) {
    if (!e) {
      return fail(500, {
        $status: 500,
        success: false,
        detail: 'Unknown error'
      });
    } else if (Object.hasOwn(e, '$status')) {
      const detail = (e as { detail: unknown }).detail;
      const field = Array.isArray(detail)
        ? detail[0].loc.join('.')
        : (e as { field: unknown }).field || undefined;
      const msg = Array.isArray(detail) ? detail[0].msg : detail || 'Unknown error';
      return fail((e as { $status: number }).$status, {
        $status: (e as { $status: number }).$status,
        success: false,
        field,
        detail: msg
      });
    } else if (e instanceof Error) {
      return fail(500, {
        $status: 500,
        success: false,
        detail: e.message
      });
    } else {
      return fail(500, {
        $status: 500,
        success: false,
        detail: JSON.stringify(e)
      });
    }
  }
};

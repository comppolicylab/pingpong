/**
 * Options
 */
export interface ForwardRequestEvent {
  fetch: any;
  request: any;
}

export interface ForwardRequestOptions {
  checkboxes?: string[];
}

type FormBody = [string, any][];

export type ForwardRequestThunk = <T extends Record<string, any>>(fetch: any, reqData: T) => Promise<any>;

export const forwardRequest = async (thunk: ForwardRequestThunk, { fetch, request}: ForwardRequestEvent, opts?: ForwardRequestOptions) => {
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

    return await thunk(fetch, reqData)
}

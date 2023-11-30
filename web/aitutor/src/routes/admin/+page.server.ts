import * as api from "$lib/api";


const forwardRequest = async (thunk, { fetch, request }) => {
    const body = await request.formData();
    console.log("BODY", body)

    const reqData = Array.from(body.entries()).reduce((agg, cur) => {
      agg[cur[0]] = cur[1];
      return agg;
    }, {});

    return await thunk(fetch, reqData)
}

export const actions = {
  createInstitution: async (event) => {
    return await forwardRequest(api.createInstitution, event);
  },
};

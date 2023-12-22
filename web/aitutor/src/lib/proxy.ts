export const forwardRequest = async (thunk, { fetch, request }) => {
    const body = await request.formData();

    const reqData = Array.from(body.entries()).reduce((agg, cur) => {
      agg[cur[0]] = cur[1];
      return agg;
    }, {});

    return await thunk(fetch, reqData)
}

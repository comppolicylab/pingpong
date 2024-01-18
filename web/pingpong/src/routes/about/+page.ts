import * as api from "$lib/api";

export async function load({fetch}) {
  const supportInfo = await api.getSupportInfo(fetch);
  return {
    supportInfo,
  };
}

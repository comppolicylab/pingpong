import type {PageLoad} from "./$types";
import * as api from "$lib/api";

export const load: PageLoad = async ({fetch}) => {
  const supportInfo = await api.getSupportInfo(fetch);
  return {
    supportInfo,
  };
}

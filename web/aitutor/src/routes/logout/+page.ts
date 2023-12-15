import {browser} from '$app/environment';
import {redirect} from "@sveltejs/kit";

export  async function load() {
  if (browser) {
    document.cookie = 'session=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
    throw redirect(302, '/login');
  }
}

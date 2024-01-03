import { fail } from "@sveltejs/kit";
import * as api from "$lib/api";
import { forwardRequest } from "$lib/proxy";

export const actions = {
  createClass: async (event) => {
    return await forwardRequest(
      async (f, d) => {
        if (!d.name) {
          return fail(400, {$status: 400, field: "name", message: "Class name is required"});
        }

        if (!d.term) {
          return fail(400, {$status: 400, field: "term", message: "Term is required"});
        }

        let instId = parseInt(d.institution, 10);
        if (!instId) {
          if (!d.newInstitution) {
            return fail(400, {$status: 400, field: "newInstitution", message: "Institution is required"});
          }
          const institution = await api.createInstitution(f, {
            name: d.newInstitution,
          });

          if (institution.$status >= 400) {
            return fail(institution.$status, {$status: institution.$status, field: "institution", message: institution.detail});
          }

          instId = institution.id;
        }

        return api.createClass(f, instId, {
          name: d.name,
          term: d.term,
        });
      }, event);
  },
};

import type { Actions } from './$types';
import * as api from '$lib/api';
import { forwardRequest } from '$lib/proxy';
import { invalid } from '$lib/validate';

export const actions: Actions = {
  /**
   * Create a new class.
   */
  createClass: async (event) => {
    return await forwardRequest(async (f, d) => {
      if (!d.name) {
        throw invalid('name', 'Class name is required');
      }

      if (!d.term) {
        throw invalid('term', 'Term is required');
      }

      let instId = parseInt(d.institution, 10);
      if (!instId) {
        if (!d.newInstitution) {
          throw invalid('institution', 'Institution is required');
        }
        const institution = await api.createInstitution(f, {
          name: d.newInstitution
        });

        if (institution.$status >= 400) {
          throw institution;
        }

        instId = institution.id;
      }

      return api.createClass(f, instId, {
        name: d.name,
        term: d.term
      });
    }, event);
  }
};

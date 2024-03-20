import { get, writable, derived, type Writable, type Readable } from "svelte/store";
import * as api from "$lib/api";

/**
 * State for the institutions manager.
 */
type InstitutionsManagerState = {
    loading: boolean;
    institutions: api.Institution[];
    error: api.Error | null;
    lastPage: boolean;
}

class InstitutionsManager {
    #fetcher: api.Fetcher;
    #data: Writable<InstitutionsManagerState>;
    #defaultPageSize: number;

    /**
     * The current list of institutions.
     */
    institutions: Readable<api.Institution[]>;

    /**
     * Any error that occurred while fetching institutions.
     */
    error: Readable<api.Error | null>;

    /**
     * Whether institutions are currently being loaded.
     */
    loading: Readable<boolean>;

    /**
     * Whether there are more institutions to fetch.
     */
    canFetchMore: Readable<boolean>;

    /**
     * Create a new institutions manager.
     */
    constructor(fetcher: api.Fetcher, defaultPageSize: number = 20) {
        this.#fetcher = fetcher;
        this.#defaultPageSize = defaultPageSize;
        this.#data = writable<InstitutionsManagerState>({
            loading: false,
            institutions: [],
            error: null,
            lastPage: false
        });

        this.institutions = derived(this.#data, $data => $data.institutions);
        this.error = derived(this.#data, $data => $data.error);
        this.loading = derived(this.#data, $data => $data.loading);
        this.canFetchMore = derived(this.#data, $data => !$data.lastPage);
    }

    /**
     * Load the first page of institutions.
     */
    async load(force: boolean = false, pageSize: number = this.#defaultPageSize) {
        const current = get(this.#data);
        if (current.loading) {
            return;
        }

        // If we're not forcing a reload and we already have institutions, don't reload.
        if (current.institutions.length > 0 && !force) {
            return;
        }

        this.#data.update($data => ({
            ...$data,
            loading: true,
            error: null,
            institutions: [],
        }));

        // TODO - handle pagination when available in the API
        const response = api.expandResponse(await api.getInstitutions(this.#fetcher, 'can_create_class'));
        if (response.error) {
            this.#data.update($data => ({
                ...$data,
                loading: false,
                error: response.error,
                institutions: [],
                lastPage: true,
            }));
            return;
        } else {
            this.#data.update($data => ({
                ...$data,
                loading: false,
                institutions: response.data.institutions,
                lastPage: true,
            }));
        }
    }

    /**
     * Load more institutions.
     */
    async loadMore(pageSize: number = this.#defaultPageSize) {
        // TODO - handle pagination when available in the API
        return;
    }
}

/**
 * The global institutions manager.
 */
let globalInstitutionsManager: InstitutionsManager | null = null;

/**
 * Get the global institutions manager.
 */
export function getInstitutionsManager(fetcher: api.Fetcher): InstitutionsManager {
    if (!globalInstitutionsManager) {
        globalInstitutionsManager = new InstitutionsManager(fetcher);
    }
    return globalInstitutionsManager;
}

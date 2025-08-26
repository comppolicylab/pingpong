import type { ColumnDef } from '@tanstack/table-core';
import { renderSnippet } from '$lib/components/ui/data-table/index.js';
import { createRawSnippet } from 'svelte';
import type { PreAssessmentStudent } from '$lib/api/types';

const noValueSnippet = createRawSnippet(() => ({
	render: () => `<div class="text-muted-foreground">No value</div>`
}));

export const columns: ColumnDef<PreAssessmentStudent>[] = [
	{
		id: 'rowNumber',
		cell: ({ row }) => row.index + 1,
		enableSorting: false,
		enableColumnFilter: false
	},
	{
		header: 'First Name',
		accessorKey: 'first_name',
		cell: ({ getValue }) => {
			const v = getValue();
			return v ? String(v) : renderSnippet(noValueSnippet, '');
		}
	},
	{
		header: 'Last Name',
		accessorKey: 'last_name',
		cell: ({ getValue }) => {
			const v = getValue();
			return v ? String(v) : renderSnippet(noValueSnippet, '');
		}
	},
	{
		header: 'Email',
		accessorKey: 'email',
		cell: ({ getValue }) => {
			const v = getValue();
			return v ? String(v) : renderSnippet(noValueSnippet, '');
		}
	},
	{
		header: 'Submission Date',
		accessorKey: 'submission_date',
		cell: ({ getValue }) => {
			const v = getValue();
			if (!v) return renderSnippet(noValueSnippet, '');

			// Parse the Eastern time string and convert to user's local timezone
			const dateStr = String(v);
			// If the string doesn't include timezone info, assume it's Eastern time
			const easternDate =
				dateStr.includes('T') &&
				(dateStr.includes('Z') || dateStr.includes('+') || dateStr.includes('-'))
					? new Date(dateStr) // Already has timezone info
					: new Date(dateStr + ' EST'); // Assume Eastern time

			return new Intl.DateTimeFormat(undefined, {
				dateStyle: 'medium',
				timeStyle: 'short'
			}).format(easternDate);
		}
	}
];

import type { ColumnDef } from '@tanstack/table-core';
import { renderComponent, renderSnippet } from '$lib/components/ui/data-table/index.js';
import UrlCopyable from './data-table-url-copyable.svelte';
import StatusBadge from './status-badge.svelte';
import RandomizationBadge from './randomization-badge.svelte';
import { createRawSnippet } from 'svelte';
import type { Course } from '$lib/api/types';

const notAssignedSnippet = createRawSnippet(() => ({
	render: () => `<div class="text-muted-foreground">Not assigned</div>`
}));
const noValueSnippet = createRawSnippet(() => ({
	render: () => `<div class="text-muted-foreground">No value</div>`
}));

export const columns: ColumnDef<Course>[] = [
	{
		header: 'Name',
		accessorKey: 'name'
	},
	{
		header: 'Status',
		accessorKey: 'status',
		cell: ({ getValue }) => renderComponent(StatusBadge, { status: String(getValue() ?? '') })
	},
	{
		header: 'Randomization',
		accessorKey: 'randomization',
		cell: ({ getValue }) =>
			getValue()
				? renderComponent(RandomizationBadge, { status: String(getValue()) })
				: renderSnippet(notAssignedSnippet, '')
	},
	{
		header: 'Start Date',
		accessorKey: 'start_date',
		cell: ({ getValue }) => {
			const v = getValue();
			return v
				? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(String(v)))
				: renderSnippet(noValueSnippet, '');
		}
	},
	{
		header: 'Enrollment',
		accessorKey: 'enrollment_count',
		cell: ({ getValue }) => {
			const v = getValue();
			return v ? String(v) : renderSnippet(noValueSnippet, '');
		}
	},
	{
		header: 'Preassessment URL',
		accessorKey: 'preassessment_url',
		cell: ({ getValue }) =>
			getValue()
				? renderComponent(UrlCopyable, { url: String(getValue()) })
				: renderSnippet(notAssignedSnippet, '')
	},
	{
		header: 'Completion Rate Target',
		accessorKey: 'completion_rate_target',
		cell: ({ getValue }) => {
			const v = getValue();
			return v ? `${v}%` : renderSnippet(noValueSnippet, '');
		}
	},

	{
		header: 'PingPong Group URL',
		accessorKey: 'pingpong_group_url',
		cell: ({ getValue }) =>
			getValue()
				? renderComponent(UrlCopyable, { url: String(getValue()) })
				: renderSnippet(notAssignedSnippet, '')
	}
];

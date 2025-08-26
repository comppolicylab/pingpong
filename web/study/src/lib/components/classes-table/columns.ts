import type { ColumnDef } from '@tanstack/table-core';
import { renderComponent, renderSnippet } from '$lib/components/ui/data-table/index.js';
import UrlCopyable from './data-table-url-copyable.svelte';
import TableButton from './data-table-button.svelte';
import StatusBadge from './status-badge.svelte';
import RandomizationBadge from './randomization-badge.svelte';
import { createRawSnippet } from 'svelte';
import type { Course } from '$lib/api/types';
import Progress from '$lib/components/completion-progress/progress.svelte';

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
		header: 'Completion Rate',
		accessorKey: 'completion_rate_target',
		cell: ({ getValue, row }) => {
			const v = getValue();
			const completionRate =
				row.original.preassessment_student_count && row.original.enrollment_count
					? Math.round(
							(row.original.preassessment_student_count / row.original.enrollment_count) * 100
						)
					: 0;
			return v
				? renderComponent(Progress, {
						target: Number(v),
						value: completionRate,
						max: 100,
						showIndicators: true
					})
				: renderSnippet(noValueSnippet, '');
		}
	},
	{
		header: 'Pre-Assessment Completion',
		id: 'actions',
		cell: ({ row }) =>
			row.original.preassessment_url
				? renderComponent(TableButton, { classId: String(row.original.id) })
				: renderSnippet(notAssignedSnippet, '')
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

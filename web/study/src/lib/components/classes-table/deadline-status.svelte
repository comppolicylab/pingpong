<script lang="ts">
	import { Badge } from '$lib/components/ui/badge/index.js';
	import AlertTriangle from '@lucide/svelte/icons/alert-triangle';
	import CalendarClock from '@lucide/svelte/icons/calendar-clock';
	import CheckIcon from '@lucide/svelte/icons/check';
	import type { Course } from '$lib/api/types';
	import { SvelteDate } from 'svelte/reactivity';

	let { course }: { course: Course } = $props();

	function toDate(v?: string) {
		if (!v) return null;
		const d = new SvelteDate(v);
		return isNaN(d.getTime()) ? null : d;
	}

	function addDays(base: Date, days: number) {
		const d = new SvelteDate(base);
		d.setDate(d.getDate() + days);
		return d;
	}

	function daysLeft(to: Date, from: Date) {
		const ms = to.getTime() - from.getTime();
		return Math.max(0, Math.ceil(ms / (1000 * 60 * 60 * 24)));
	}

	const state = $derived.by(() => {
		const now = new SvelteDate();

		const start = toDate(course.start_date);
		const target =
			typeof course.completion_rate_target === 'number' ? course.completion_rate_target : undefined;
		const enrollment =
			typeof course.enrollment_count === 'number' ? course.enrollment_count : undefined;
		const completed =
			typeof course.preassessment_student_count === 'number'
				? course.preassessment_student_count
				: 0;

		if (!start || !target || !enrollment || enrollment <= 0) {
			return { kind: 'missing' as const };
		}

		const pct = Math.round((completed / enrollment) * 100);
		if (pct >= target) {
			return { kind: 'met' as const };
		}

		const due = addDays(start, 15);
		const grace = addDays(start, 22);

		if (now < start) {
			return { kind: 'upcoming' as const, days: daysLeft(due, now) };
		} else if (now <= due) {
			return { kind: 'due' as const, days: daysLeft(due, now) };
		} else if (now <= grace) {
			return { kind: 'grace' as const, days: daysLeft(grace, now) };
		}
		return { kind: 'risk' as const };
	});

	function label() {
		switch (state.kind) {
			case 'met':
				return 'Target met';
			case 'due':
				return `Due in ${state.days}d`;
			case 'grace':
				return `Grace: ${state.days}d left`;
			case 'upcoming':
				return `Due soon (${state.days}d)`;
			case 'risk':
				return 'At risk';
			default:
				return 'Missing info';
		}
	}

	function variant(): 'default' | 'secondary' | 'destructive' {
		switch (state.kind) {
			case 'met':
				return 'default';
			case 'risk':
				return 'destructive';
			case 'due':
			case 'grace':
			case 'upcoming':
			default:
				return 'secondary';
		}
	}

	function Icon() {
		switch (state.kind) {
			case 'met':
				return CheckIcon;
			case 'risk':
			case 'grace':
			case 'due':
			case 'upcoming':
				return CalendarClock;
			default:
				return AlertTriangle;
		}
	}
</script>

<Badge variant={variant()} class="inline-flex items-center gap-1">
	{#if Icon() === CheckIcon}
		<CheckIcon size={14} />
	{:else if Icon() === CalendarClock}
		<CalendarClock size={14} />
	{:else}
		<AlertTriangle size={14} />
	{/if}
	{label()}
</Badge>

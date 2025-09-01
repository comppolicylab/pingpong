<script lang="ts">
	import type { Course } from '$lib/api/types';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import Check from '@lucide/svelte/icons/check';
	import Clock from '@lucide/svelte/icons/clock';
	import Hourglass from '@lucide/svelte/icons/hourglass';
	import AlertTriangle from '@lucide/svelte/icons/alert-triangle';
	import Calendar from '@lucide/svelte/icons/calendar';
	import { SvelteDate } from 'svelte/reactivity';

	let { course }: { course: Course | undefined } = $props();

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
	function addWeeks(base: Date, weeks: number) {
		return addDays(base, weeks * 7);
	}
	function fmtDate(d?: Date | null) {
		if (!d) return '—';
		return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(d);
	}
	function daysLeft(to?: Date | null) {
		if (!to) return undefined;
		const ms = to.getTime() - now.getTime();
		if (ms < 0) return 0;
		return Math.ceil(ms / (1000 * 60 * 60 * 24));
	}
	function daysLabel(n?: number) {
		if (typeof n !== 'number') return '';
		return `${n} ${n === 1 ? 'day' : 'days'}`;
	}
	function statusDotClass(status: string) {
		switch (status) {
			case 'completed':
				return 'bg-gradient-to-b from-emerald-400 to-emerald-600 ';
			case 'active':
				return 'bg-gradient-to-b from-sky-400 to-sky-600 ';
			case 'grace':
				return 'bg-gradient-to-b from-amber-300 to-amber-500 ';
			case 'incomplete':
				return 'bg-gradient-to-b from-red-400 to-red-600 ';
			case 'upcoming':
			default:
				return 'bg-gradient-to-b from-neutral-300 to-neutral-400 dark:from-neutral-700 dark:to-neutral-600';
		}
	}

	const start = $derived(toDate(course?.start_date));
	const now = $derived(new SvelteDate());
	const due = $derived(start ? addWeeks(start, 2) : null);
	const grace = $derived(start ? addWeeks(start, 3) : null);

	const target = $derived(
		typeof course?.completion_rate_target === 'number' ? course.completion_rate_target : undefined
	);
	const enrollment = $derived(
		typeof course?.enrollment_count === 'number' ? course.enrollment_count : undefined
	);
	const completed = $derived(
		typeof course?.preassessment_student_count === 'number' ? course.preassessment_student_count : 0
	);
	const pct = $derived(
		enrollment && enrollment > 0 ? Math.round((completed / enrollment) * 100) : undefined
	);

	function statusRegistration() {
		return 'completed';
	}
	function statusEligibility() {
		if (course?.status === 'accepted') return 'completed';
		if (course?.status === 'in_review') return 'active';
		return 'upcoming';
	}
	function statusPreLink() {
		if (!start) return 'upcoming';
		const linkStart = addDays(start, -7);
		if (now < linkStart) return 'upcoming';
		if (now < start) return 'active';
		return 'completed';
	}
	function statusAdministerPre() {
		if (!start) return 'upcoming';
		const windowEnd = addWeeks(start, 2);
		if (now < start) return 'upcoming';
		if (now < windowEnd) return 'active';
		// After the administration window ends, keep this step incomplete
		// if the checkpoint is still in grace or incomplete
		const checkpoint = statusCheckpointPre();
		if (checkpoint === 'grace' || checkpoint === 'incomplete') return 'incomplete';
		return 'completed';
	}
	function statusCheckpointPre() {
		if (!start || !target || !enrollment || enrollment <= 0) return 'upcoming';
		// Show upcoming until the checkpoint (due date)
		if (now < (due as Date)) return 'upcoming';
		if (pct !== undefined && pct >= target) return 'completed';
		// Only becomes relevant at or after the checkpoint (due date)
		if (now < (due as Date)) return 'upcoming';
		if (now <= (grace as Date)) return 'grace';
		return 'incomplete';
	}
	function statusTreatmentDemo() {
		if (course?.randomization !== 'treatment') return 'upcoming';
		if (!start) return 'upcoming';
		const startAfterTwo = addWeeks(start, 2);
		const wrap = addWeeks(start, 4);
		if (now < startAfterTwo) return 'upcoming';
		if (now <= wrap) return 'active';
		return 'completed';
	}
	function statusThroughout() {
		if (!start) return 'upcoming';
		// Do not move to Throughout until checkpoint is completed (target met) and the checkpoint date has passed
		const checkpointDone =
			typeof target === 'number' &&
			typeof enrollment === 'number' &&
			enrollment > 0 &&
			typeof pct === 'number' &&
			pct >= target &&
			now >= (due as Date);
		if (checkpointDone && now >= start) return 'active';
		return 'upcoming';
	}

	function Step({
		idx,
		title,
		date,
		description,
		status
	}: {
		idx: number;
		title: string;
		date?: string;
		description?: string;
		status: string;
	}) {
		return {
			idx,
			title,
			date,
			description,
			status
		};
	}

	const steps = $derived.by(() => {
		const list: Array<ReturnType<typeof Step>> = [];

		list.push(
			Step({
				idx: 1,
				title: 'Complete Study Registration',
				status: statusRegistration()
			})
		);

		list.push(
			Step({
				idx: 2,
				title: 'Checkpoint: Eligibility Confirmation & Study Enrollment',
				description:
					'Our team will confirm eligibility and enrollment. If admitted, you agree not to use other customized generative AI teaching tools during the study.',
				status: statusEligibility()
			})
		);

		list.push(
			Step({
				idx: 3,
				title: 'Receive Pre-Study Assessment Link',
				date: start ? `By ${fmtDate(addDays(start, -7))}` : '1 week before course start',
				description:
					'We will provide a unique link for your class so students can complete the pre-study assessment.',
				status: statusPreLink()
			})
		);

		list.push(
			Step({
				idx: 4,
				title: 'Administer Pre-Study Assessment',
				date: start
					? `${fmtDate(start)} – ${fmtDate(addWeeks(start, 2))}`
					: 'First 2 weeks of class',
				description:
					'Assign the Pre-Study Assessment as a required assignment due in the first two weeks.',
				status: statusAdministerPre()
			})
		);

		list.push(
			Step({
				idx: 5,
				title: 'Checkpoint: Pre-Study Assessment Completion',
				date: start ? fmtDate(due) : '2 weeks after course start',
				description:
					'Last day to meet your pre-assessment completion target to continue in the study. First honorarium installment follows after all your courses meet their targets.',
				status: statusCheckpointPre()
			})
		);

		if (course?.randomization === 'treatment') {
			list.push(
				Step({
					idx: 6,
					title: 'Conduct PingPong Demo',
					date: start ? `After ${fmtDate(addWeeks(start, 2))}` : 'After 2 weeks of class',
					description:
						'After your course is confirmed as continuing with the study, our team will provide you with resources to conduct a brief demo to help students understand how to use PingPong.',
					status: statusTreatmentDemo()
				})
			);
		}

		list.push(
			Step({
				idx: 7,
				title:
					course?.randomization === 'treatment'
						? 'Integrate PingPong into an Assignment'
						: 'Throughout the semester',
				description:
					course?.randomization === 'treatment'
						? 'To support meaningful engagement, we ask that you commit to integrating at least one PingPong-based assignment into your course this semester.'
						: 'Teach as usual. This class will not receive access to the PingPong platform for this semester.',
				status: statusThroughout()
			})
		);

		list.push(
			Step({
				idx: 8,
				title: 'Receive Post-Study Assessment Link',
				date: '2 weeks before course end',
				description: 'We will provide a unique link for your class for the post-study assessment.',
				status: 'upcoming'
			})
		);
		list.push(
			Step({
				idx: 9,
				title: 'Administer Post-Study Assessment',
				date: 'Last 2 weeks of class',
				description:
					'Assign the Post-Study Assessment as a required assignment due in the last two weeks.',
				status: 'upcoming'
			})
		);
		list.push(
			Step({
				idx: 10,
				title: 'Checkpoint: Post-Study Assessment Completion',
				date: 'Last day of class',
				description:
					'Last day to meet your post-assessment completion target to complete the study.',
				status: 'upcoming'
			})
		);
		list.push(
			Step({
				idx: 11,
				title: 'Checkpoint: Instructor Survey Completion',
				date: '1 week after course end',
				description:
					'Last day to submit the Instructor Experience Survey and complete the study. Second honorarium installment and any bonuses follow after all your courses meet their targets.',
				status: 'upcoming'
			})
		);
		list.push(
			Step({
				idx: 12,
				title: 'Treatment & Control: Free Access to PingPong',
				date: 'After study conclusion',
				description:
					'After the study concludes, both treatment and control group classes that completed the study are eligible for one semester of free access to PingPong.',
				status: 'upcoming'
			})
		);

		return list;
	});

	// Ensure only one step is considered the current "active" item
	const timelineSteps = $derived.by(() => {
		const items = steps;
		// Prefer the oldest of the items that is active
		let currentActiveIndex = -1;
		for (let i = 0; i < items.length; i++) {
			const s = items[i];
			if (s?.status === 'active') {
				currentActiveIndex = i;
				break;
			}
		}
		// Map to a displayStatus where only the current active remains 'active'
		return items.map((s, i) => ({
			...s,
			displayStatus:
				i === currentActiveIndex ? s.status : s.status === 'active' ? 'upcoming' : s.status
		}));
	});
</script>

<div class="rounded-md border p-4">
	<h2 class="mb-3 text-lg font-semibold">Timeline</h2>
	{#if !course}
		<div class="space-y-2">
			<div class="h-4 w-full rounded bg-muted"></div>
			<div class="h-4 w-3/4 rounded bg-muted"></div>
			<div class="h-4 w-2/3 rounded bg-muted"></div>
			<div class="h-4 w-4/5 rounded bg-muted"></div>
		</div>
	{:else}
		<div class="relative ml-1">
			<div class="absolute top-0 bottom-0 left-[11px] w-px bg-muted-foreground/20"></div>
			<ol class="space-y-5">
				{#each timelineSteps as s (s.idx)}
					<li class="relative pl-8">
						<span
							class="absolute top-1.5 left-[5px] inline-block size-3 rounded-full {statusDotClass(
								s.displayStatus
							)}"
						></span>
						<div class="flex w-full flex-wrap items-center justify-between gap-2 pr-2">
							<h3 class="min-w-0 leading-tight font-medium">{s.title}</h3>
							<div class="shrink-0">
								{#if s.displayStatus === 'completed'}
									<Badge
										variant="outline"
										class="border-emerald-600 bg-transparent text-emerald-600 [a&]:hover:bg-transparent"
									>
										<Check />
										Completed
									</Badge>
								{:else if s.displayStatus === 'active'}
									{#if s.title === 'Administer Pre-Study Assessment'}
										<Badge
											variant="outline"
											class="border-sky-600 bg-transparent text-sky-600 [a&]:hover:bg-transparent"
										>
											<Clock />
											{daysLabel(daysLeft(addWeeks(start as Date, 2)))} left
										</Badge>
									{:else}
										<Badge
											variant="outline"
											class="border-sky-600 bg-transparent text-sky-600 [a&]:hover:bg-transparent"
										>
											<Clock />
											Now
										</Badge>
									{/if}
								{:else if s.displayStatus === 'grace'}
									<Badge
										variant="outline"
										class="border-amber-600 bg-transparent text-amber-700 dark:border-amber-400 dark:text-amber-300 [a&]:hover:bg-transparent"
									>
										<Hourglass />
										Grace period / {daysLabel(daysLeft(addWeeks(start as Date, 3)))} left
									</Badge>
								{:else if s.displayStatus === 'incomplete'}
									<Badge
										variant="outline"
										class="border-red-600 bg-transparent text-red-600 [a&]:hover:bg-transparent"
									>
										<AlertTriangle />
										Incomplete
									</Badge>
								{:else}
									<Badge
										variant="outline"
										class="border-muted-foreground/50 bg-transparent text-muted-foreground [a&]:hover:bg-transparent"
									>
										<Calendar />
										Upcoming
									</Badge>
								{/if}
							</div>
						</div>
						{#if s.date}
							<div class="mt-1 text-xs text-muted-foreground">{s.date}</div>
						{/if}
						{#if s.description}
							<p class="mt-1 text-sm text-muted-foreground">{s.description}</p>
						{/if}
					</li>
				{/each}
			</ol>
		</div>
		{#if !start}
			<p class="mt-3 text-xs text-muted-foreground">
				Set a start date to activate date-based milestones.
			</p>
		{/if}
	{/if}
</div>

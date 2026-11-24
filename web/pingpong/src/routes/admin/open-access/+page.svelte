<script lang="ts">
	import type { ComponentProps } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import {
		Badge,
		Button,
		Chart,
		Input,
		Label,
		Select,
		Table,
		TableBody,
		TableBodyCell,
		TableBodyRow,
		TableHead,
		TableHeadCell
	} from 'flowbite-svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import type { OpenAccessGranularity, OpenAccessUsageRow } from '$lib/api';
	import { headerState } from '$lib/stores/header';
	import dayjs from '$lib/time';

	type ChartOptions = ComponentProps<InstanceType<typeof Chart>>['options'];
	type Metric = 'cost' | 'tokens' | 'runs' | 'tts';
	type Tier = OpenAccessUsageRow['tier'];

	let { data } = $props();

	const TIERS: { tier: Tier; label: string; color: string }[] = [
		{ tier: 'anonymous', label: 'Anonymous', color: '#2a78d6' },
		{ tier: 'registered', label: 'Signed up', color: '#eb6834' }
	];
	const SIGNUP_COLOR = '#6250d6';
	const METRICS: { value: Metric; name: string }[] = [
		{ value: 'cost', name: 'Estimated cost' },
		{ value: 'tokens', name: 'OpenAI tokens' },
		{ value: 'runs', name: 'AI replies' },
		{ value: 'tts', name: 'Speech characters' }
	];
	const GRANULARITIES: { value: OpenAccessGranularity; name: string }[] = [
		{ value: 'day', name: 'Day' },
		{ value: 'week', name: 'Week' },
		{ value: 'month', name: 'Month' }
	];

	const usage = $derived(data.usage);
	const priced = $derived(usage.rows.some((row) => row.openai_cost + row.speech_cost > 0));
	let metric = $state<Metric | null>(null);
	const activeMetric = $derived(metric ?? (priced ? 'cost' : 'tokens'));
	let start = $derived(data.start);
	let end = $derived(data.end);
	let granularity = $derived<OpenAccessGranularity>(data.granularity);

	const isNewHeaderLayout = $derived(data.forceCollapsedLayout && data.forceShowSidebarButton);
	$effect(() => {
		if (isNewHeaderLayout) {
			headerState.set({
				kind: 'nongroup',
				props: { title: 'Open Access usage', redirectUrl: '/admin', redirectName: 'Admin page' }
			});
		}
	});

	const integer = new Intl.NumberFormat();
	const compact = new Intl.NumberFormat(undefined, { notation: 'compact' });
	const dollars = new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' });

	const value = (row: OpenAccessUsageRow, which: Metric) =>
		which === 'cost'
			? row.openai_cost + row.speech_cost
			: which === 'tokens'
				? row.input_tokens + row.output_tokens
				: which === 'runs'
					? row.runs
					: row.tts_characters;
	const format = (amount: number, which: Metric) =>
		which === 'cost' ? dollars.format(amount) : integer.format(Math.round(amount));
	const axis = (amount: number, which: Metric) =>
		which === 'cost' ? dollars.format(amount) : compact.format(amount);
	const sum = (rows: OpenAccessUsageRow[], which: Metric) =>
		rows.reduce((total, row) => total + value(row, which), 0);

	const periodLabel = (period: string) => {
		const day = dayjs(period);
		if (usage.granularity === 'month') return day.format('MMM YYYY');
		if (usage.granularity === 'week') return `Week of ${day.format('MMM D')}`;
		return day.format('MMM D');
	};
	const lessonLabel = (assistantId: number | null) => {
		const lesson = usage.lessons.find((item) => item.assistant_id === assistantId);
		return lesson ? `${lesson.number}. ${lesson.name ?? 'Untitled'}` : 'Other';
	};

	const baseOptions = (which: Metric): ChartOptions => ({
		chart: {
			type: 'bar',
			stacked: true,
			height: 320,
			fontFamily: 'inherit',
			toolbar: { show: false },
			animations: { enabled: false }
		},
		dataLabels: { enabled: false },
		stroke: { width: 2, colors: ['#ffffff'] },
		grid: { borderColor: '#e5e7eb', strokeDashArray: 4 },
		legend: { position: 'top', horizontalAlign: 'left', fontSize: '13px' },
		tooltip: { shared: true, intersect: false, y: { formatter: (amount) => format(amount, which) } }
	});

	const overTime = $derived<ChartOptions>({
		...baseOptions(activeMetric),
		colors: TIERS.map((tier) => tier.color),
		series: TIERS.map(({ tier, label }) => ({
			name: label,
			data: usage.periods.map((period) =>
				sum(
					usage.rows.filter((row) => row.period === period && row.tier === tier),
					activeMetric
				)
			)
		})),
		plotOptions: {
			bar: {
				columnWidth: '60%',
				borderRadius: 4,
				borderRadiusApplication: 'end',
				borderRadiusWhenStacked: 'last'
			}
		},
		xaxis: { categories: usage.periods.map(periodLabel), labels: { hideOverlappingLabels: true } },
		yaxis: { labels: { formatter: (amount) => axis(amount, activeMetric) } }
	});

	const lessonIds = $derived([
		...usage.lessons.map((lesson) => lesson.assistant_id),
		...(usage.rows.some(
			(row) => !usage.lessons.some((lesson) => lesson.assistant_id === row.assistant_id)
		)
			? [null]
			: [])
	]);
	const byLesson = $derived<ChartOptions>({
		...baseOptions(activeMetric),
		chart: {
			...baseOptions(activeMetric).chart,
			height: Math.max(200, lessonIds.length * 44 + 80)
		},
		colors: TIERS.map((tier) => tier.color),
		series: TIERS.map(({ tier, label }) => ({
			name: label,
			data: lessonIds.map((assistantId) =>
				sum(
					usage.rows.filter(
						(row) =>
							row.tier === tier &&
							(assistantId === null
								? !usage.lessons.some((lesson) => lesson.assistant_id === row.assistant_id)
								: row.assistant_id === assistantId)
					),
					activeMetric
				)
			)
		})),
		plotOptions: {
			bar: {
				horizontal: true,
				barHeight: '60%',
				borderRadius: 4,
				borderRadiusApplication: 'end',
				borderRadiusWhenStacked: 'last'
			}
		},
		xaxis: {
			categories: lessonIds.map(lessonLabel),
			labels: { formatter: (amount) => axis(Number(amount), activeMetric) }
		},
		yaxis: { labels: { maxWidth: 260 } }
	});

	const signupsOverTime = $derived<ChartOptions>({
		...baseOptions('runs'),
		chart: { ...baseOptions('runs').chart, stacked: false, height: 240 },
		colors: [SIGNUP_COLOR],
		legend: { show: false },
		series: [
			{
				name: 'Sign-ups',
				data: usage.periods.map(
					(period) => usage.signups.find((item) => item.period === period)?.signups ?? 0
				)
			}
		],
		plotOptions: { bar: { columnWidth: '60%', borderRadius: 4, borderRadiusApplication: 'end' } },
		xaxis: { categories: usage.periods.map(periodLabel), labels: { hideOverlappingLabels: true } },
		yaxis: { labels: { formatter: (amount) => compact.format(amount) } }
	});

	const totals = $derived({
		cost: sum(usage.rows, 'cost'),
		openai: usage.rows.reduce((total, row) => total + row.openai_cost, 0),
		speech: usage.rows.reduce((total, row) => total + row.speech_cost, 0),
		runs: sum(usage.rows, 'runs'),
		input: usage.rows.reduce((total, row) => total + row.input_tokens, 0),
		output: usage.rows.reduce((total, row) => total + row.output_tokens, 0),
		tts: sum(usage.rows, 'tts'),
		signups: usage.signups.reduce((total, item) => total + item.signups, 0)
	});

	const tableRows = $derived(
		lessonIds.flatMap((assistantId) =>
			TIERS.map(({ tier, label }) => {
				const rows = usage.rows.filter(
					(row) =>
						row.tier === tier &&
						(assistantId === null
							? !usage.lessons.some((lesson) => lesson.assistant_id === row.assistant_id)
							: row.assistant_id === assistantId)
				);
				return {
					key: `${assistantId}-${tier}`,
					lesson: lessonLabel(assistantId),
					tier: label,
					runs: sum(rows, 'runs'),
					input: rows.reduce((total, row) => total + row.input_tokens, 0),
					output: rows.reduce((total, row) => total + row.output_tokens, 0),
					tts: sum(rows, 'tts'),
					openai: rows.reduce((total, row) => total + row.openai_cost, 0),
					speech: rows.reduce((total, row) => total + row.speech_cost, 0),
					cost: sum(rows, 'cost')
				};
			}).filter((row) => row.runs > 0)
		)
	);

	const today = dayjs();
	const isToday = $derived(usage.start === today.format('YYYY-MM-DD') && usage.end === usage.start);
	const presets = [
		{ name: 'Today', start: today, end: today, granularity: 'day' },
		{
			name: 'This week',
			start: today.subtract((today.day() + 6) % 7, 'day'),
			end: today,
			granularity: 'day'
		},
		{ name: 'This month', start: today.startOf('month'), end: today, granularity: 'day' },
		{
			name: 'Last month',
			start: today.subtract(1, 'month').startOf('month'),
			end: today.subtract(1, 'month').endOf('month'),
			granularity: 'day'
		},
		{ name: 'This year', start: today.startOf('year'), end: today, granularity: 'month' }
	] as const;

	const show = (next: { start: string; end: string; granularity: OpenAccessGranularity }) => {
		const params = new URLSearchParams(next);
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- resolve() takes no query string
		goto(`${resolve('/admin/open-access')}?${params}`, { keepFocus: true, noScroll: true });
	};
</script>

<div class="flex h-full w-full flex-col">
	{#if !isNewHeaderLayout}
		<PageHeader>
			<h2 class="text-color-blue-dark-50 px-4 pt-6 pb-3 font-serif text-3xl font-bold" slot="left">
				Open Access usage
			</h2>
		</PageHeader>
	{/if}

	<div class="flex flex-col gap-10 overflow-y-auto p-8 sm:p-12">
		<section class="flex flex-col gap-6">
			{#if usage.limits.paused}
				<Badge color="red" class="self-start">Paused</Badge>
			{:else if usage.limits.anonymous_paused}
				<Badge color="yellow" class="self-start">Paused for anonymous visitors</Badge>
			{/if}
			<div class="flex flex-wrap items-end gap-4">
				<div class="flex flex-wrap gap-2">
					{#each presets as preset (preset.name)}
						<Button
							size="sm"
							color="alternative"
							onclick={() =>
								show({
									start: preset.start.format('YYYY-MM-DD'),
									end: preset.end.format('YYYY-MM-DD'),
									granularity: preset.granularity
								})}>{preset.name}</Button
						>
					{/each}
				</div>
				<div>
					<Label for="oa-start" class="mb-1 text-xs">From</Label>
					<Input id="oa-start" type="date" size="sm" bind:value={start} />
				</div>
				<div>
					<Label for="oa-end" class="mb-1 text-xs">To</Label>
					<Input id="oa-end" type="date" size="sm" bind:value={end} />
				</div>
				<div>
					<Label for="oa-granularity" class="mb-1 text-xs">Group by</Label>
					<Select
						id="oa-granularity"
						size="sm"
						items={GRANULARITIES}
						bind:value={granularity}
						placeholder=""
					/>
				</div>
				<Button
					size="sm"
					class="bg-orange text-white hover:bg-orange-dark"
					disabled={!start || !end || end < start}
					onclick={() => show({ start, end, granularity })}>Show</Button
				>
				<div class="ml-auto">
					<Label for="oa-metric" class="mb-1 text-xs">Measure</Label>
					<Select
						id="oa-metric"
						size="sm"
						items={METRICS}
						value={activeMetric}
						onchange={(event) => (metric = (event.target as HTMLSelectElement).value as Metric)}
						placeholder=""
					/>
				</div>
			</div>
			<div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
				<div class="rounded-2xl bg-gold-light p-5">
					<div class="text-sm text-gray-700">Estimated cost</div>
					<div class="mt-1 text-3xl font-light">{dollars.format(totals.cost)}</div>
					<div class="text-sm text-gray-700">
						{dollars.format(totals.openai)} OpenAI · {dollars.format(totals.speech)} speech
					</div>
				</div>
				<div class="rounded-2xl bg-gold-light p-5">
					<div class="text-sm text-gray-700">AI replies</div>
					<div class="mt-1 text-3xl font-light">{integer.format(totals.runs)}</div>
					{#if isToday && usage.limits.daily_turns !== null}
						<div class="text-sm text-gray-700">
							of {integer.format(usage.limits.daily_turns)} daily
						</div>
					{/if}
				</div>
				<div class="rounded-2xl bg-gold-light p-5">
					<div class="text-sm text-gray-700">OpenAI tokens</div>
					<div class="mt-1 text-3xl font-light">{compact.format(totals.input + totals.output)}</div>
					<div class="text-sm text-gray-700">
						{compact.format(totals.input)} in · {compact.format(totals.output)} out
					</div>
					{#if isToday && usage.limits.daily_openai_tokens !== null}
						<div class="text-sm text-gray-700">
							of {compact.format(usage.limits.daily_openai_tokens)} daily
						</div>
					{/if}
				</div>
				<div class="rounded-2xl bg-gold-light p-5">
					<div class="text-sm text-gray-700">Speech characters</div>
					<div class="mt-1 text-3xl font-light">{compact.format(totals.tts)}</div>
					{#if isToday && usage.limits.daily_tts_characters !== null}
						<div class="text-sm text-gray-700">
							of {compact.format(usage.limits.daily_tts_characters)} daily
						</div>
					{/if}
				</div>
				<div class="rounded-2xl bg-gold-light p-5">
					<div class="text-sm text-gray-700">Sign-ups</div>
					<div class="mt-1 text-3xl font-light">{integer.format(totals.signups)}</div>
				</div>
			</div>

			<div class="rounded-2xl border border-gray-200 p-4">
				<h4 class="px-2 font-medium">
					{METRICS.find((item) => item.value === activeMetric)?.name} by {usage.granularity}
				</h4>
				<Chart options={overTime} />
			</div>

			<div class="grid gap-6 lg:grid-cols-2">
				<div class="rounded-2xl border border-gray-200 p-4">
					<h4 class="px-2 font-medium">
						{METRICS.find((item) => item.value === activeMetric)?.name} by lesson
					</h4>
					<Chart options={byLesson} />
				</div>
				<div class="rounded-2xl border border-gray-200 p-4">
					<h4 class="px-2 font-medium">Sign-ups by {usage.granularity}</h4>
					<Chart options={signupsOverTime} />
				</div>
			</div>

			<Table>
				<TableHead>
					<TableHeadCell>Lesson</TableHeadCell>
					<TableHeadCell>Learners</TableHeadCell>
					<TableHeadCell class="text-right">AI replies</TableHeadCell>
					<TableHeadCell class="text-right">Input tokens</TableHeadCell>
					<TableHeadCell class="text-right">Output tokens</TableHeadCell>
					<TableHeadCell class="text-right">Speech characters</TableHeadCell>
					<TableHeadCell class="text-right">OpenAI cost</TableHeadCell>
					<TableHeadCell class="text-right">Speech cost</TableHeadCell>
					<TableHeadCell class="text-right">Estimated cost</TableHeadCell>
				</TableHead>
				<TableBody>
					{#each tableRows as row (row.key)}
						<TableBodyRow>
							<TableBodyCell>{row.lesson}</TableBodyCell>
							<TableBodyCell>{row.tier}</TableBodyCell>
							<TableBodyCell class="text-right">{integer.format(row.runs)}</TableBodyCell>
							<TableBodyCell class="text-right">{integer.format(row.input)}</TableBodyCell>
							<TableBodyCell class="text-right">{integer.format(row.output)}</TableBodyCell>
							<TableBodyCell class="text-right">{integer.format(row.tts)}</TableBodyCell>
							<TableBodyCell class="text-right">{dollars.format(row.openai)}</TableBodyCell>
							<TableBodyCell class="text-right">{dollars.format(row.speech)}</TableBodyCell>
							<TableBodyCell class="text-right">{dollars.format(row.cost)}</TableBodyCell>
						</TableBodyRow>
					{:else}
						<TableBodyRow>
							<TableBodyCell colspan={9} class="text-center text-gray-600">
								No AI replies in this period.
							</TableBodyCell>
						</TableBodyRow>
					{/each}
				</TableBody>
			</Table>

			<h4 class="font-medium">Top users</h4>
			<Table>
				<TableHead>
					<TableHeadCell>Subject</TableHeadCell>
					<TableHeadCell>Learner</TableHeadCell>
					<TableHeadCell class="text-right">AI replies</TableHeadCell>
					<TableHeadCell class="text-right">Input tokens</TableHeadCell>
					<TableHeadCell class="text-right">Output tokens</TableHeadCell>
					<TableHeadCell class="text-right">Speech characters</TableHeadCell>
					<TableHeadCell class="text-right">OpenAI cost</TableHeadCell>
					<TableHeadCell class="text-right">Speech cost</TableHeadCell>
					<TableHeadCell class="text-right">Estimated cost</TableHeadCell>
					<TableHeadCell>Last active</TableHeadCell>
				</TableHead>
				<TableBody>
					{#each usage.top_users as user (user.subject)}
						<TableBodyRow>
							<TableBodyCell class="font-mono text-xs select-all">{user.subject}</TableBodyCell>
							<TableBodyCell>{TIERS.find((item) => item.tier === user.tier)?.label}</TableBodyCell>
							<TableBodyCell class="text-right">{integer.format(user.runs)}</TableBodyCell>
							<TableBodyCell class="text-right">{integer.format(user.input_tokens)}</TableBodyCell>
							<TableBodyCell class="text-right">{integer.format(user.output_tokens)}</TableBodyCell>
							<TableBodyCell class="text-right">{integer.format(user.tts_characters)}</TableBodyCell
							>
							<TableBodyCell class="text-right">{dollars.format(user.openai_cost)}</TableBodyCell>
							<TableBodyCell class="text-right">{dollars.format(user.speech_cost)}</TableBodyCell>
							<TableBodyCell class="text-right"
								>{dollars.format(user.openai_cost + user.speech_cost)}</TableBodyCell
							>
							<TableBodyCell>{dayjs(user.last_active).format('MMM D, h:mm A')}</TableBodyCell>
						</TableBodyRow>
					{:else}
						<TableBodyRow>
							<TableBodyCell colspan={10} class="text-center text-gray-600">
								No AI replies in this period.
							</TableBodyCell>
						</TableBodyRow>
					{/each}
				</TableBody>
			</Table>
		</section>
	</div>
</div>

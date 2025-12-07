<script lang="ts">
  import type { StatusComponentUpdate } from '$lib/api';
  import { slide } from 'svelte/transition';

  export let assistantStatusUpdates: StatusComponentUpdate[] = [];

  const IMPACT_STYLES: Record<
    string,
    {
      dot: string;
      text: string;
    }
  > = {
    critical: { dot: 'bg-red-600', text: 'text-red-700' },
    major: { dot: 'bg-yellow-500', text: 'text-yellow-700' },
    minor: { dot: 'bg-amber-400', text: 'text-amber-700' },
    maintenance: { dot: 'bg-sky-500', text: 'text-sky-700' },
    none: { dot: 'bg-gray-400', text: 'text-gray-600' }
  };

  const getImpactStyle = (impact: string | null | undefined) => {
    const key = (impact ?? 'none').toLowerCase();
    return IMPACT_STYLES[key] ?? IMPACT_STYLES.none;
  };

  const formatStatusStep = (step: string | null | undefined) => {
    if (!step) {
      return 'Update';
    }
    return step
      .replace(/_/g, ' ')
      .split(' ')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  const IMPACT_PRIORITY = ['critical', 'major', 'minor', 'maintenance', 'none'] as const;

  const normalizeImpact = (impact: string | null | undefined) => {
    const normalized = (impact ?? 'none').toString().trim().toLowerCase();
    return normalized.length > 0 ? normalized : 'none';
  };

  const getImpactRank = (impact: string) => {
    const normalizedImpact = normalizeImpact(impact);
    const rank = IMPACT_PRIORITY.indexOf(normalizedImpact as (typeof IMPACT_PRIORITY)[number]);
    return rank === -1 ? IMPACT_PRIORITY.length - 1 : rank;
  };

  const getMostSevereImpact = (updates: StatusComponentUpdate[]) => {
    if (!updates.length) {
      return 'none';
    }

    return (
      updates.reduce<string>((current, update) => {
        const candidate = normalizeImpact(update.impact);

        if (!current) {
          return candidate;
        }

        return getImpactRank(candidate) < getImpactRank(current) ? candidate : current;
      }, '') || 'none'
    );
  };

  let showAllIssues = false;

  $: hasMultipleIssues = assistantStatusUpdates.length > 1;
  $: activeIssueCount = assistantStatusUpdates.length;
  $: summaryImpactStyle = getImpactStyle(getMostSevereImpact(assistantStatusUpdates));
  $: showDetails = hasMultipleIssues ? showAllIssues : activeIssueCount > 0;
  $: summaryLabel = `${activeIssueCount} active issues affecting this assistant`;

  $: if (!hasMultipleIssues && showAllIssues) {
    showAllIssues = false;
  }
</script>

{#if assistantStatusUpdates.length > 0}
  <div class="mb-2 w-full text-xs xl:text-sm text-gray-700">
    <div class="mx-4 flex flex-col gap-1.5">
      {#if hasMultipleIssues}
        <button
          type="button"
          class="flex w-full items-center gap-3 text-left text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-600 transition focus:outline-hidden focus-visible:ring-2 focus-visible:ring-sky-400/60 focus-visible:ring-offset-2 hover:text-gray-800"
          on:click={() => (showAllIssues = !showAllIssues)}
          aria-expanded={showAllIssues}
        >
          <span class="flex flex-1 items-center" aria-hidden="true">
            <span class="block h-px w-full bg-gray-200"></span>
          </span>
          <span class={`flex flex-none items-center whitespace-nowrap ${summaryImpactStyle.text}`}>
            <span class="px-2 text-center">{summaryLabel}</span>
          </span>
          <span class="flex flex-1 items-center" aria-hidden="true">
            <span class="block h-px w-full bg-gray-200"></span>
          </span>
          <span
            class="inline-flex h-4 w-4 flex-none items-center justify-center text-gray-400 transition-transform duration-200 ease-out"
          >
            <svg
              class={`h-3 w-3 ${showAllIssues ? 'rotate-180' : ''}`}
              viewBox="0 0 20 20"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <path
                d="M5 8l5 5 5-5"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </span>
        </button>
      {/if}

      {#if showDetails}
        <div class="flex flex-col gap-1.5" transition:slide={{ duration: 220 }}>
          {#each assistantStatusUpdates as statusUpdate (statusUpdate.incidentId)}
            {@const impactStyle = getImpactStyle(statusUpdate.impact)}
            <div
              class={`flex w-full min-w-0 items-baseline gap-2.5 ${impactStyle.text}`}
              title={statusUpdate.incidentName}
            >
              <span
                class={`inline-block h-2 w-2 shrink-0 rounded-full -mr-1 ${impactStyle.dot}`}
                aria-hidden="true"
              ></span>
              <div class="flex min-w-0 items-baseline gap-2">
                <span class="text-xs font-semibold uppercase tracking-wide whitespace-nowrap">
                  {formatStatusStep(statusUpdate.updateStatus)}
                </span>
                <span class="truncate leading-snug">
                  {statusUpdate.incidentName}
                </span>
              </div>
              <!-- eslint-disable svelte/no-navigation-without-resolve -->
              <a
                class="shrink-0 text-xs font-semibold underline"
                href={statusUpdate.shortlink || 'https://pingpong-hks.statuspage.io'}
                target="_blank"
                rel="noopener noreferrer"
              >
                View more...
              </a>
              <!-- eslint-enable svelte/no-navigation-without-resolve -->
            </div>
          {/each}
        </div>
      {/if}
    </div>
  </div>
{/if}

<script lang="ts">
  import type { StatusComponentUpdate } from '$lib/api';

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
</script>

{#if assistantStatusUpdates.length > 0}
  <div class="mb-2 max-w-full text-xs xl:text-sm text-gray-700">
    <div class="flex flex-col gap-0.5 mx-4">
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
          <a
            class="shrink-0 text-xs font-semibold underline"
            href={statusUpdate.shortlink || 'https://pingpong-hks.statuspage.io'}
            target="_blank"
            rel="noopener noreferrer"
          >
            View more...
          </a>
        </div>
      {/each}
    </div>
  </div>
{/if}

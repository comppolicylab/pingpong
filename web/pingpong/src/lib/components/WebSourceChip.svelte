<script lang="ts">
  import type { WebSearchSource } from '$lib/api';
  import { happyToast } from '$lib/toast';
  import { parse } from 'tldts';

  export let source: WebSearchSource;

  const domainFromUrl = (url?: string | null) => {
    if (!url) return '';
    const parsed = parse(url);
    if (parsed.domain) {
      return parsed.domain;
    }
    try {
      const parsedUrl = new URL(url);
      return parsedUrl.hostname;
    } catch (err) {
      console.error('Invalid URL provided to WebSourceChip', err);
      return url;
    }
  };

  const domain = domainFromUrl(source?.url);
  const faviconUrl = source?.url
    ? `https://www.google.com/s2/favicons?domain_url=${encodeURIComponent(source.url)}&sz=64`
    : undefined;

  const label = source?.name || domain || source?.url || 'Source';

  const showToast = () => {
    const namePart = source?.name ? `${source.name}\n` : '';
    const urlPart = source?.url || 'No URL provided';
    happyToast(`${namePart}${urlPart}`, 5000);
  };
</script>

<button
  type="button"
  class="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-100"
  on:click|stopPropagation={showToast}
>
  {#if faviconUrl}
    <img alt="Favicon" src={faviconUrl} class="h-4 w-4 rounded-full" loading="lazy" />
  {/if}
  <span class="truncate max-w-[12rem]" title={source?.name || domain}>{label}</span>
</button>

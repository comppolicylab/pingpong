<script lang="ts">
  import { type CanvasClass } from '$lib/api';
  import DropdownBadge from './DropdownBadge.svelte';
  import DropdownOption from './DropdownOption.svelte';
  export let canvasClasses: CanvasClass[];
  export let classNodes: { [key: string]: HTMLElement };
  export let selectedClass: string;
  export let updateSelectedClass: (id: string) => void;
  const colorPalletes = [
    'border-pastel-green-400 from-pastel-green-50 to-pastel-green-100 text-pastel-green-800',
    'border-sunset-orange-400 from-sunset-orange-50 to-sunset-orange-100 text-sunset-orange-800',
    'border-red-pink-400 from-red-pink-50 to-red-pink-100 text-red-pink-800',
    'border-lightning-yellow-400 from-lightning-yellow-50 to-lightning-yellow-100 text-lightning-yellow-800',
    'border-electric-violet-400 from-electric-violet-50 to-electric-violet-100 text-electric-violet-800',
    'border-copper-rust-400 from-copper-rust-50 to-copper-rust-100 text-copper-rust-800',
    'border-shakespeare-blue-400 from-shakespeare-blue-50 to-shakespeare-blue-100 text-shakespeare-blue-800',
    'border-salem-green-400 from-salem-green-50 to-salem-green-100 text-salem-green-800',
    'border-red-purple-400 from-red-purple-50 to-red-purple-100 text-red-purple-800',
    'border-royal-blue-400 from-royal-blue-50 to-royal-blue-100 text-royal-blue-800',
    'border-opal-400 from-opal-50 to-opal-100 text-opal-800',
    'border-chalet-green-400 from-chalet-green-50 to-chalet-green-100 text-chalet-green-800',
    'border-monza-red-400 from-monza-red-50 to-monza-red-100 text-monza-red-800',
    'border-chalet-green-400 from-chalet-green-50 to-chalet-green-100 text-chalet-green-800',
    'border-monza-red-400 from-monza-red-50 to-monza-red-100 text-monza-red-800'
  ];
  const termsInList = [...new Set(canvasClasses.map((c) => c.term || 'Unknown term'))];
  const termToColor = termsInList.reduce(
    (acc, term, index) => {
      const color = colorPalletes[index % colorPalletes.length];
      acc[term] = color;
      return acc;
    },
    {} as { [key: string]: string }
  );
</script>

<div class="relative z-0">
  {#each canvasClasses as { id, name, course_code, term }}
    <div bind:this={classNodes[id.toString()]}>
      <DropdownOption
        value={id.toString()}
        name={course_code || 'Unknown course'}
        subtitle={(name || 'Unknown course') + ' (' + id.toString() + ')'}
        selectedValue={selectedClass}
        update={updateSelectedClass}
      >
        <DropdownBadge
          extraClasses={termToColor[term || 'Unknown term'] ||
            'border-amber-400 from-amber-50 to-amber-100 text-amber-700'}
          ><span slot="name">{term || 'Unknown term'}</span></DropdownBadge
        >
      </DropdownOption>
    </div>
  {/each}
</div>

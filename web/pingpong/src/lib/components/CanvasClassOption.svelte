<script lang="ts">
  import { Badge, DropdownItem } from 'flowbite-svelte';
  import { ImageOutline, StarSolid } from 'flowbite-svelte-icons';
  export let value: string;
  export let selectedClass: string;
  export let updateSelectedClass: (class_id: string) => void;
  export let course_code: string;
  export let course_name: string;
  export let term: string;

  const hashString = (str: string) => {
    const prime1 = 31; // Prime number for season
  const prime2 = 37; // Prime number for year
  
  let seasonHash = 0;
  let yearHash = 0;
  
  // Split the input string into season and year
  const parts = str.split(' ');
  const season = parts[0];
  const year = parseInt(parts[1]);

  // Hash the season part
  for (let i = 0; i < season.length; i++) {
    seasonHash = (seasonHash * prime1) + season.charCodeAt(i);
  }

  // Hash the year part
  yearHash = year * prime2;

  // Combine the hashes
  let combinedHash = seasonHash + yearHash;

  // Ensure the combined hash remains within the bounds of a 32-bit integer
  combinedHash |= 0;

  console.log(`Hashed ${str} to ${combinedHash}`);
  return combinedHash;
}


  const getTailwindColorName = (str: string) => {
    const colorPalletes = [
      {bg: 'forest-light', text: 'forest-dark'},
      {bg: 'sun-light', text: 'sun-dark'},
      {bg: 'pink-light', text: 'pink-dark'},
      {bg: 'salmon-light', text: 'salmon-dark'},
      {bg: 'red-light', text: 'red-dark'},
      {bg: 'vibrant-pink-light', text: 'vibrant-pink-dark'},
      {bg: 'sky-blue-light', text: 'sky-blue-dark'},
      {bg: 'clay-light', text: 'clay-dark'},
      {bg: 'grayish-blue-light', text: 'grayish-blue-dark'},
      {bg: 'bright-green-light', text: 'bright-green-dark'},
      {bg: 'calm-blue-light', text: 'calm-blue-dark'},
      {bg: 'bright-red-light', text: 'bright-red-dark'},
      {bg: 'bronze-light', text: 'bronze-dark'},
      {bg: 'thyme-light', text: 'thyme-dark'},
      {bg: 'cloudy-blue-light', text: 'cloudy-blue-dark'},
      {bg: 'bright-orange-light', text: 'bright-orange-dark'},
      {bg: 'purple-light', text: 'purple-dark'},
      {bg: 'pinkish-light', text: 'pinkish-dark'},
    ];
    const index = Math.abs(hashString(str)) % colorPalletes.length;
    return colorPalletes[index];
  };

  const color = getTailwindColorName(term)
</script>

<DropdownItem
  on:click={() => updateSelectedClass(value)}
  defaultClass={value == selectedClass
    ? 'flex flex-col gap-x-1 font-medium py-2 px-4 text-sm text-blue-900 bg-blue-light-50 hover:bg-blue-light-50 hover:text-blue-900'
    : 'flex flex-col gap-x-1 font-medium py-2 px-4 text-sm text-[{color.text}] bg-[{color.bg}] hover:bg-gray-100 dark:hover:bg-gray-600'}
>
  <div class="flex flex-row gap-x-3 w-full flex-wrap items-center justify-between">
    <div class='text-lg'>{course_code}</div>
    <div class="flex flex-row gap-x-1 gap-y-0.5 flex-wrap items-center">
        <Badge
        color="none"
          class="flex flex-row items-center text-gold-dark bg-{color.bg} gap-x-1 py-0.5 px-2 text-xs normal-case"
          >{term}</Badge
        >
    </div>
  </div>
  <span class="font-normal">{course_name}</span>
</DropdownItem>

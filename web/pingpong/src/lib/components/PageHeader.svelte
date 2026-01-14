<script lang="ts" context="module">
  export const mainTextClass = 'text-3xl text-color-blue-dark-50 font-serif font-bold px-4';
</script>

<header
  class="bg-blue-light-50 p-2 pb-6 pt-6 lg:p-8 lg:pb-4 lg:pt-10 sm:flex sm:pb-2 justify-between items-center"
>
  <div class="grow">
    <slot name="left" />
  </div>
  <div class="ml-2 mt-4 sm:ml-0 sm:mt-0">
    <slot name="right" />
  </div>
</header>

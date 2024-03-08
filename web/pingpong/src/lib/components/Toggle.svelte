<script context="module" lang="ts">
  /**
   * Event data for the toggle change event.
   */
  export type ToggleChangeEventDetail = {
    checked: boolean;
    target: HTMLInputElement;
  };

  /**
   * Custom event for the toggle change event.
   */
  export type ToggleChangeEvent = CustomEvent<ToggleChangeEventDetail>;
</script>

<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  /**
   * Whether the checkbox is checked or not.
   */
  export let checked: boolean;
  /**
   * The name of the checkbox form element.
   */
  export let name: string;
  /**
   * The color of the toggle when it is active.
   *
   * Default is Tailwind green-500.
   */
  export let activeColor: string = '#22c55e';
  /**
   * The color of the toggle when it is inactive.
   *
   * Default is Tailwind gray-200.
   */
  export let inactiveColor: string = '#e5e7eb';

  // Underlying form element
  let checkBox: HTMLInputElement;

  // Custom events dispatcher
  const dispatcher = createEventDispatcher();

  /**
   * Handle toggling the checkbox.
   */
  const handleChange = (evt: Event) => {
    checked = !checked;
    checkBox.checked = checked;
    const detail: ToggleChangeEventDetail = {
      checked: checked,
      target: checkBox
    };
    dispatcher('change', detail);
  };

  /**
   * Keyboard event handler. Responds to `Enter` as a mouse click.
   */
  const handleKeyDown = (evt: KeyboardEvent) => {
    if (evt.key === 'Enter') {
      handleChange(evt);
    }
  };

  // Current color of the toggle
  $: bgColor = checked ? activeColor : inactiveColor;
</script>

<div
  class="toggle"
  class:active={checked}
  aria-roledescription="toggle"
  role="switch"
  aria-checked={checked}
  tabindex="0"
  on:click={handleChange}
  on:keydown={handleKeyDown}
>
  <input type="checkbox" {name} {checked} bind:this={checkBox} />
  <span class="toggle-ui" style={`background-color: ${bgColor}`} />
</div>

<style lang="css">
  .toggle {
    position: relative;
    display: inline-block;
    width: 40px;
    height: 24px;
    cursor: pointer;
  }

  .toggle input {
    display: none;
  }

  .toggle-ui {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    border-radius: 12px;
    transition: 0.1s;
    background-color: white;
    border: 1px solid #ddd;
  }

  .toggle-ui:before {
    position: absolute;
    content: '';
    height: 20px;
    width: 20px;
    left: 1px;
    bottom: 1px;
    top: 1px;
    background-color: white;
    border: 1px solid #ddd;
    border-radius: 50%;
    transition: 0.1s;
  }

  .toggle.active .toggle-ui:before {
    transform: translateX(16px);
  }
</style>

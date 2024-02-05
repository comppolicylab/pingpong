/** @type {import('tailwindcss').Config}*/
const config = {
  content: [
    './src/**/*.{html,js,svelte,ts}',
    './node_modules/flowbite-svelte/**/*.{html,js,svelte,ts}'
  ],

  darkMode: 'class',

  theme: {
    container: {
      center: true,
      padding: '2rem'
    },
    extend: {}
  },

  plugins: [require('flowbite/plugin')]
};

module.exports = config;

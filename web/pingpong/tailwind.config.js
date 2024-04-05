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
    extend: {
      borderRadius: {
        '4xl': '2rem',
      },
      colors: {
        'darkblue': '#201E45',
        'lightblue': '#F1F4FF',
      },
    }
  },

  plugins: [require('flowbite/plugin')]
};

module.exports = config;

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
    fontFamily: {
      sans: ['Inter', 'sans-serif'],
      serif: ['STIX Two Text', 'serif']
    },
    extend: {
      borderRadius: {
        '4xl': '2rem'
      },
      borderWidth: {
        3: '3px'
      },
      colors: {
        'blue-dark-50': '#201E45',
        'blue-dark-40': '#2D2A62',
        'blue-dark-30': '#545193',
        'blue-light-50': '#F1F4FF',
        'blue-light-40': '#D9E2FF',
        'orange': '#FC624D',
        'orange-dark': '#E33F0C',
        'orange-light': '#FFF7F1',
        'gold': '#FFD076',
        'gold-light': '#FFF6E4'
      }
    }
  },

  plugins: [require('flowbite/plugin')]
};

module.exports = config;

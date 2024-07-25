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
        orange: '#FC624D',
        'orange-dark': '#E33F0C',
        'orange-light': '#FFF7F1',
        gold: '#FFD076',
        'gold-light': '#FFF6E4',
        'forest-light': '#c7ebc8',
        'forest-dark': '#2b6a2f',
        'sun-light': '#f5e293',
        'sun-dark': '#965712',
        'pink-light': '#ffcbcd',
        'pink-dark': '#a60b29',
        'salmon-light': '#fcd7cc',
        'salmon-dark': '#7b3521',
        'red-light': '#ffc7a5',
        'red-dark': '#a1160b',
        'vibrant-pink-light': '#ffcaf1',
        'vibrant-pink-dark': '#ab0962',
        'sky-blue-light': '#bfdefe',
        'sky-blue-dark': '#1e408a',
        'clay-light': '#f2dc95',
        'clay-dark': '#85401b',
        'grayish-light': '#e8e2e5',
        'grayish-dark': '#625257',
        'bright-green-light': '#aeffc8',
        'bright-green-dark': '#066126',
        'calm-blue-light': '#bee4f9',
        'calm-blue-dark': '#124768',
        'bright-red-light': '#ffc3bf',
        'bright-red-dark': '#ab0a00',
        'bronze-light': '#f0d5b8',
        'bronze-dark': '#833e29',
        'thyme-light': '#d7dbbb',
        'thyme-dark': '#42482c',
        'cloudy-blue-light': '#c9d1d8',
        'cloudy-blue-dark': '#363b43',
        'bright-orange-light': '#f4e494',
        'bright-orange-dark': '#7b4718',
        'purple-light': '#e7d2ff',
        'purple-dark': '#54148f',
        'pinkish-light': '#f4d6e2',
        'pinkish-dark': '#872d41',
      }
    }
  },

  plugins: [require('flowbite/plugin')]
};

module.exports = config;

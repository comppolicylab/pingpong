<!-- Display a top navigation bar for the page. -->
<script>
  import { Heading, Navbar, NavBrand, NavUl, NavLi, NavHamburger } from "flowbite-svelte";
  import Logo from './Logo.svelte';

</script>


<Navbar color="none">
  <NavBrand href="/">
    <Logo size="8" color="amber-600" />
    <Heading customSize="text-xl" tag="h1" class="text-amber-500 pl-4">AI Tutor</Heading>
  </NavBrand>
  <NavHamburger />
  <NavUl>
    <NavLi href="/" class="text-white">Home</NavLi>
    <NavLi href="/about" class="text-white">About</NavLi>
    <NavLi href="/logout" class="text-white">Logout</NavLi>
  </NavUl>
</Navbar>

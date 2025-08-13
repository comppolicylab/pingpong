<script lang="ts">
	// Types
	import type { ComponentProps } from 'svelte';

	// State
	import { page } from '$app/state';

	// Icons
	import Building2 from '@lucide/svelte/icons/building-2';
	import LayoutDashboard from '@lucide/svelte/icons/layout-dashboard';
	import BookOpenTextIcon from '@lucide/svelte/icons/book-open-text';

	// Components
	import * as Sidebar from '$lib/components/ui/sidebar/index.js';

	// Snippets
	import NavUser from './nav-user.svelte';

	let { ref = $bindable(null), ...restProps }: ComponentProps<typeof Sidebar.Root> = $props();

	const data = $derived(page.data);
</script>

<Sidebar.Root bind:ref variant="inset" {...restProps}>
	<Sidebar.Header>
		<Sidebar.Menu>
			<Sidebar.MenuItem>
				<Sidebar.MenuButton size="lg">
					{#snippet child({ props })}
						<a href="/" {...props}>
							<div
								class="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground"
							>
								<Building2 class="size-4" />
							</div>
							<div class="grid flex-1 text-left text-sm leading-tight">
								<span class="truncate font-medium">PingPong College Study</span>
								<span class="truncate text-xs">Fall 2025</span>
							</div>
						</a>
					{/snippet}
				</Sidebar.MenuButton>
			</Sidebar.MenuItem>
		</Sidebar.Menu>
	</Sidebar.Header>
	<Sidebar.Content>
		<Sidebar.Group>
			<Sidebar.Menu>
				<Sidebar.MenuItem>
					<Sidebar.MenuButton tooltipContent="Dashboard" isActive={page.url.pathname === '/'}>
						{#snippet child({ props })}
							<a href="/" {...props}>
								<LayoutDashboard class="size-4" />
								<span>Dashboard</span>
							</a>
						{/snippet}
					</Sidebar.MenuButton>
				</Sidebar.MenuItem>
			</Sidebar.Menu>
		</Sidebar.Group>
		<Sidebar.Group>
			<Sidebar.GroupLabel>Support</Sidebar.GroupLabel>
			<Sidebar.Menu>
				<Sidebar.MenuItem>
					<Sidebar.MenuButton
						tooltipContent="Resources"
						isActive={page.url.pathname === '/resources'}
					>
						{#snippet child({ props })}
							<a href="/resources" {...props}>
								<BookOpenTextIcon />
								<span>Resources</span>
							</a>
						{/snippet}
					</Sidebar.MenuButton>
				</Sidebar.MenuItem>
			</Sidebar.Menu>
		</Sidebar.Group>
	</Sidebar.Content>
	<Sidebar.Footer>
		<NavUser
			user={{
				name: data.instructor?.first_name + ' ' + data.instructor?.last_name,
				email: data.instructor?.academic_email
			}}
		/>
	</Sidebar.Footer>
</Sidebar.Root>

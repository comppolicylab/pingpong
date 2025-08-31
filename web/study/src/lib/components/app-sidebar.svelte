<script lang="ts">
	// Types
	import type { ComponentProps } from 'svelte';

	// State
	import { page } from '$app/state';

	// Icons
	import Building2 from '@lucide/svelte/icons/building-2';
	import LayoutDashboard from '@lucide/svelte/icons/layout-dashboard';
	import BookOpenTextIcon from '@lucide/svelte/icons/book-open-text';
	import ContactIcon from '@lucide/svelte/icons/contact';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';

	// Components
	import * as Sidebar from '$lib/components/ui/sidebar/index.js';
	import * as Collapsible from '$lib/components/ui/collapsible/index.js';

	// Snippets
	import NavUser from './nav-user.svelte';
	import type { Course } from '$lib/api/types';
	import { onMount } from 'svelte';
	import SidebarMenuSkeleton from '$lib/components/ui/sidebar/sidebar-menu-skeleton.svelte';
	import {
		courses as coursesStore,
		loading as coursesLoading,
		ensureCourses
	} from '$lib/stores/courses';

	let { ref = $bindable(null), ...restProps }: ComponentProps<typeof Sidebar.Root> = $props();

	const data = $derived(page.data);

	onMount(async () => {
		try {
			await ensureCourses(fetch);
		} catch {
			// ignore, skeleton/no-courses will show
		}
	});

	const courses = $derived.by(() => {
		const filtered: Course[] = ($coursesStore ?? []).filter(
			(cls) => cls.preassessment_url && cls.preassessment_url !== '' && cls.status === 'accepted'
		);
		return filtered;
	});
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
				<Collapsible.Root open class="group/collapsible">
					<Sidebar.MenuItem>
						<Collapsible.Trigger>
							{#snippet child({ props })}
								<Sidebar.MenuButton
									{...props}
									isActive={page.url.pathname.startsWith('/preassessment')}
								>
									<ContactIcon />
									<span>Pre-Assessment Details</span>
									<ChevronRightIcon
										class="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-90"
									/>
								</Sidebar.MenuButton>
							{/snippet}
						</Collapsible.Trigger>
						<Collapsible.Content>
							<Sidebar.MenuSub>
								{#if $coursesLoading}
									<SidebarMenuSkeleton showIcon />
									<SidebarMenuSkeleton showIcon />
									<SidebarMenuSkeleton showIcon />
									<SidebarMenuSkeleton showIcon />
								{:else if (courses ?? []).length === 0}
									<Sidebar.MenuSubItem>
										<Sidebar.MenuSubButton aria-disabled={true}>
											<span class="text-muted-foreground">No courses</span>
										</Sidebar.MenuSubButton>
									</Sidebar.MenuSubItem>
								{:else}
									{#each courses ?? [] as subItem (subItem.name)}
										<Sidebar.MenuSubItem>
											<Sidebar.MenuSubButton
												isActive={page.url.pathname === `/preassessment/${subItem.id}`}
											>
												{#snippet child({ props })}
													<a href={`/preassessment/${subItem.id}`} {...props}>
														<span>{subItem.name}</span>
													</a>
												{/snippet}
											</Sidebar.MenuSubButton>
										</Sidebar.MenuSubItem>
									{/each}
								{/if}
							</Sidebar.MenuSub>
						</Collapsible.Content>
					</Sidebar.MenuItem>
				</Collapsible.Root>
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

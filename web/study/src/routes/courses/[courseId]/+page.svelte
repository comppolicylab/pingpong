<script lang="ts">
	import * as Alert from '$lib/components/ui/alert/index.js';
	import * as Table from '$lib/components/ui/table/index.js';
	import Info from '@lucide/svelte/icons/info';
	import Progress from '$lib/components/completion-progress/progress.svelte';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import type { Course, PreAssessmentStudent, PostAssessmentStudent } from '$lib/api/types';
	import { deletePreAssessmentStudent, getPreAssessmentStudents } from '$lib/api/client';
	import { explodeResponse } from '$lib/api/utils';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import { courses as coursesStore, ensureCourses } from '$lib/stores/courses';
	import StatusBadge from '$lib/components/classes-table/status-badge.svelte';
	import RandomizationBadge from '$lib/components/classes-table/randomization-badge.svelte';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import UrlCopyField from '$lib/components/url-copy-field.svelte';
	import CourseTimeline from '$lib/components/course-timeline.svelte';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import { Input } from '$lib/components/ui/input/index.js';
	import * as Dialog from '$lib/components/ui/dialog/index.js';
	import Check from '@lucide/svelte/icons/check';
	import Clock from '@lucide/svelte/icons/clock';
	import Hourglass from '@lucide/svelte/icons/hourglass';
	import AlertTriangle from '@lucide/svelte/icons/alert-triangle';
	import { SvelteDate, SvelteMap, SvelteSet } from 'svelte/reactivity';
	import { toast } from 'svelte-sonner';
	import { updateCourseEnrollment } from '$lib/api/client';
	import { slide } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import Trash from '@lucide/svelte/icons/trash';
	import CheckCircle from '@lucide/svelte/icons/check-circle';
	import CircleOff from '@lucide/svelte/icons/circle-off';
	import Calendar from '@lucide/svelte/icons/calendar';
	import CircleHelp from '@lucide/svelte/icons/circle-help';

	let preAssessmentStudents = $state([] as PreAssessmentStudent[]);
	let postAssessmentStudents = $state([] as PostAssessmentStudent[]);
	let loading = $state(true);
	// eslint-disable-next-line svelte/no-unnecessary-state-wrap
	let preExpandedStudents = $state(new SvelteSet<string>());
	// eslint-disable-next-line svelte/no-unnecessary-state-wrap
	let postExpandedStudents = $state(new SvelteSet<string>());
	let confirmingStudent = $state<StudentRosterEntry | null>(null);
	let confirmationValue = $state('');
	let deletingStudent = $state(false);
	let showRemovalDialog = $state(false);

	type StudentRosterEntry = {
		id: string;
		first_name?: string;
		last_name?: string;
		name?: string;
		email?: string;
		pre_submissions: PreAssessmentStudent[];
		post_submissions: PostAssessmentStudent[];
		removed?: boolean;
	};

	const course = $derived(
		($coursesStore as Course[]).find((c) => c.id === (page.params.courseId as string))
	);
	const isTreatmentCourse = $derived(course?.randomization === 'treatment');

	onMount(async () => {
		try {
			const courseId = page.params.courseId as string;
			const [studentsRes] = await Promise.all([
				getPreAssessmentStudents(fetch, courseId).then(explodeResponse),
				ensureCourses(fetch)
			]);
			preAssessmentStudents = studentsRes.pre_assessment_submissions ?? [];
			postAssessmentStudents = studentsRes.post_assessment_submissions ?? [];
		} catch {
			// Leave defaults; error could be surfaced in future UX
		} finally {
			loading = false;
		}
	});

	function toDate(v?: string) {
		if (!v) return null;
		const d = new SvelteDate(v);
		return isNaN(d.getTime()) ? null : d;
	}
	function addDays(base: Date, days: number) {
		const d = new SvelteDate(base);
		d.setDate(d.getDate() + days);
		return d;
	}
	function daysLeft(to: Date, from: Date) {
		const ms = to.getTime() - from.getTime();
		return Math.max(0, Math.ceil(ms / (1000 * 60 * 60 * 24)));
	}
	function daysLabel(n?: number) {
		if (typeof n !== 'number') return '';
		return `${n} ${n === 1 ? 'day' : 'days'}`;
	}

	function parseSubmissionDate(value?: string) {
		if (!value) return null;
		const dateStr = String(value);
		const easternDate =
			dateStr.includes('T') &&
			(dateStr.includes('Z') || dateStr.includes('+') || dateStr.includes('-'))
				? new Date(dateStr)
				: new Date(`${dateStr} EST`);
		return isNaN(easternDate.getTime()) ? null : easternDate;
	}

	function formatSubmissionDate(value?: string) {
		const parsed = parseSubmissionDate(value);
		if (!parsed) return '';
		return new Intl.DateTimeFormat(undefined, {
			dateStyle: 'medium',
			timeStyle: 'short'
		}).format(parsed);
	}

	function studentKeyFromSubmission(submission: PreAssessmentStudent | PostAssessmentStudent) {
		const studentKey =
			typeof submission.student_id === 'string' && submission.student_id.trim()
				? submission.student_id.trim()
				: undefined;
		const emailKey =
			typeof submission.email === 'string' ? submission.email.toLowerCase().trim() : undefined;
		return studentKey || emailKey || submission.id;
	}

	function isPreSubmission(
		submission: PreAssessmentStudent | PostAssessmentStudent
	): submission is PreAssessmentStudent {
		return 'first_name' in submission || 'last_name' in submission;
	}

	function isPostSubmission(
		submission: PreAssessmentStudent | PostAssessmentStudent
	): submission is PostAssessmentStudent {
		return 'status' in submission || 'name' in submission;
	}

	const studentRoster = $derived.by<StudentRosterEntry[]>(() => {
		const groups = new SvelteMap<string, StudentRosterEntry>();

		function upsertSubmission(
			submission: PreAssessmentStudent | PostAssessmentStudent,
			kind: 'pre' | 'post'
		) {
			const key = studentKeyFromSubmission(submission);

			const existing =
				groups.get(key) ??
				({
					id: key,
					first_name: isPreSubmission(submission) ? submission.first_name : undefined,
					last_name: isPreSubmission(submission) ? submission.last_name : undefined,
					name: isPostSubmission(submission) ? submission.name : undefined,
					email: submission.email,
					pre_submissions: [],
					post_submissions: [],
					removed: false
				} satisfies StudentRosterEntry);

			if (isPreSubmission(submission) && submission.first_name && !existing.first_name) {
				existing.first_name = submission.first_name;
			}
			if (isPreSubmission(submission) && submission.last_name && !existing.last_name) {
				existing.last_name = submission.last_name;
			}
			if (isPostSubmission(submission) && submission.name && !existing.name) {
				existing.name = submission.name;
			}
			if (submission.email && !existing.email) existing.email = submission.email;
			const submissionRemoved = 'removed' in submission && submission.removed ? true : false;
			if (submissionRemoved) existing.removed = true;

			if (kind === 'pre') {
				existing.pre_submissions = [
					...existing.pre_submissions,
					submission as PreAssessmentStudent
				];
			} else {
				existing.post_submissions = [
					...existing.post_submissions,
					submission as PostAssessmentStudent
				];
			}

			groups.set(key, existing);
		}

		preAssessmentStudents.forEach((s) => upsertSubmission(s, 'pre'));
		postAssessmentStudents.forEach((s) => upsertSubmission(s, 'post'));

		const roster: StudentRosterEntry[] = [];

		for (const entry of groups.values()) {
			const pre_submissions = [...entry.pre_submissions].sort((a, b) => {
				const aDate = parseSubmissionDate(a.submission_date)?.getTime() ?? 0;
				const bDate = parseSubmissionDate(b.submission_date)?.getTime() ?? 0;
				return aDate - bDate; // oldest first
			});
			const post_submissions = [...entry.post_submissions].sort((a, b) => {
				const aDate = parseSubmissionDate(a.submission_date)?.getTime() ?? 0;
				const bDate = parseSubmissionDate(b.submission_date)?.getTime() ?? 0;
				return aDate - bDate; // oldest first
			});

			const latest =
				pre_submissions[pre_submissions.length - 1] ??
				post_submissions[post_submissions.length - 1];
			const latestPre: PreAssessmentStudent | undefined =
				latest && isPreSubmission(latest) ? latest : undefined;
			const latestPost: PostAssessmentStudent | undefined =
				latest && isPostSubmission(latest) ? latest : undefined;
			const anyRemoved =
				entry.removed ||
				removedStudentKeys.has(entry.id) ||
				pre_submissions.some((s) => s.removed) ||
				post_submissions.some((s) => s.removed);

			roster.push({
				...entry,
				first_name: latestPre?.first_name ?? entry.first_name,
				last_name: latestPre?.last_name ?? entry.last_name,
				name: latestPost?.name ?? entry.name,
				email: latest?.email ?? entry.email,
				pre_submissions,
				post_submissions,
				removed: anyRemoved
			});
		}

		roster.sort((a, b) => {
			const aRemoved = isRemoved(a.removed);
			const bRemoved = isRemoved(b.removed);
			if (aRemoved !== bRemoved) return aRemoved ? 1 : -1;
			const last = (a.last_name || a.name || '').localeCompare(b.last_name || b.name || '');
			if (last !== 0) return last;
			const first = (a.first_name || '').localeCompare(b.first_name || '');
			if (first !== 0) return first;
			return (a.email || '').localeCompare(b.email || '');
		});

		return roster;
	});
	const activeRoster = $derived(studentRoster.filter((s) => !isRemoved(s.removed)));
	const removedRoster = $derived(studentRoster.filter((s) => isRemoved(s.removed)));

	function formatLastFirst(first?: string, last?: string, fallback?: string) {
		if (first && last) return `${last}, ${first}`;
		if (last) return last;
		if (first) return first;
		if (fallback) return fallback;
		return '—';
	}

	function studentName(student: StudentRosterEntry) {
		return formatLastFirst(student.first_name, student.last_name, student.name || student.email);
	}

	function submissionDisplayName(submission: PreAssessmentStudent | PostAssessmentStudent) {
		const first = 'first_name' in submission ? submission.first_name : undefined;
		const last = 'last_name' in submission ? submission.last_name : undefined;
		const fallback = 'name' in submission ? submission.name || submission.email : submission.email;
		return formatLastFirst(first, last, fallback);
	}

	function togglePreSubmissions(studentId: string) {
		const next = new SvelteSet(preExpandedStudents);
		if (next.has(studentId)) {
			next.delete(studentId);
		} else {
			next.add(studentId);
		}
		preExpandedStudents = next;
	}
	function togglePostSubmissions(studentId: string) {
		const next = new SvelteSet(postExpandedStudents);
		if (next.has(studentId)) {
			next.delete(studentId);
		} else {
			next.add(studentId);
		}
		postExpandedStudents = next;
	}
	function primarySubmissionId(student: StudentRosterEntry) {
		const latestPre = student.pre_submissions[student.pre_submissions.length - 1];
		const latestPost = student.post_submissions[student.post_submissions.length - 1];
		return latestPre?.id ?? latestPost?.id;
	}
	function studentGroupKey(student: StudentRosterEntry) {
		return student.id;
	}
	function isRemoved(removed?: boolean) {
		return !!removed;
	}
	function openRemovalDialog(student: StudentRosterEntry) {
		confirmingStudent = student;
		confirmationValue = '';
		showRemovalDialog = true;
	}
	function closeRemovalDialog() {
		confirmingStudent = null;
		confirmationValue = '';
		deletingStudent = false;
		showRemovalDialog = false;
	}
	const canConfirmRemoval = $derived(!!confirmingStudent && confirmationValue.trim() === 'delete');
	async function submitRemovalRequest() {
		if (!confirmingStudent) return;
		const submissionId = primarySubmissionId(confirmingStudent);
		if (!submissionId) {
			toast.error('No submission found for this student.');
			return;
		}
		deletingStudent = true;
		try {
			const courseId = page.params.courseId as string;
			const res = await deletePreAssessmentStudent(fetch, courseId, submissionId);
			if (res.$status && res.$status >= 300) {
				throw new Error(res?.detail?.toString() || 'Failed to remove student.');
			}
			const targetKey = studentGroupKey(confirmingStudent);
			preAssessmentStudents = preAssessmentStudents.map((s) =>
				studentKeyFromSubmission(s) === targetKey ? { ...s, removed: true } : s
			);
			postAssessmentStudents = postAssessmentStudents.map((s) =>
				studentKeyFromSubmission(s) === targetKey ? { ...s, removed: true } : s
			);
			toast.success('Student removed. A confirmation email will be sent to your email.');
			closeRemovalDialog();
		} catch (err) {
			toast.error(err instanceof Error ? err.message : 'Failed to remove student.');
		} finally {
			deletingStudent = false;
		}
	}
	$effect(() => {
		if (!showRemovalDialog) {
			confirmingStudent = null;
			confirmationValue = '';
			deletingStudent = false;
		}
	});
	const enrollmentCount = $derived(course?.enrollment_count);
	const preAssessmentStudentCount = $derived(course?.preassessment_student_count);
	const postAssessmentStudentCount = $derived(course?.postassessment_student_count);
	const completionRateTarget = $derived(course?.completion_rate_target);
	const completionRate = $derived(
		typeof enrollmentCount === 'number' &&
			enrollmentCount > 0 &&
			typeof preAssessmentStudentCount === 'number'
			? Math.round((preAssessmentStudentCount / enrollmentCount) * 100)
			: 0
	);
	const postCompletionRate = $derived(
		typeof enrollmentCount === 'number' &&
			enrollmentCount > 0 &&
			typeof postAssessmentStudentCount === 'number'
			? Math.round((postAssessmentStudentCount / enrollmentCount) * 100)
			: 0
	);
	const removedStudentKeys = $derived.by(() => {
		const keys = new SvelteSet<string>();
		for (const submission of preAssessmentStudents) {
			if (submission.removed) keys.add(studentKeyFromSubmission(submission));
		}
		for (const submission of postAssessmentStudents) {
			if (submission.removed) keys.add(studentKeyFromSubmission(submission));
		}
		return keys;
	});
	const activePreSubmissions = $derived(
		preAssessmentStudents.filter(
			(s) => !s.removed && !removedStudentKeys.has(studentKeyFromSubmission(s))
		)
	);
	const activePostSubmissions = $derived(
		postAssessmentStudents.filter(
			(s) => !s.removed && !removedStudentKeys.has(studentKeyFromSubmission(s))
		)
	);

	const postDeadlines = $derived.by(() => {
		const now = new SvelteDate();
		const end = toDate(course?.end_date);
		const target =
			typeof course?.completion_rate_target === 'number'
				? course?.completion_rate_target
				: undefined;
		const enrollment =
			typeof course?.enrollment_count === 'number' ? course?.enrollment_count : undefined;
		const completed =
			typeof course?.postassessment_student_count === 'number'
				? course?.postassessment_student_count
				: 0;

		if (!end || !target || !enrollment || enrollment <= 0) {
			return { kind: 'missing' as const, due: null as Date | null, grace: null as Date | null };
		}

		const pct = Math.round((completed / enrollment) * 100);
		const due = addDays(end, 1);
		const grace = addDays(end, 8);
		const notShowBefore = addDays(end, -22);

		if (now < notShowBefore) {
			return { kind: 'upcoming' as const, due, grace, days: daysLeft(due, now) };
		}
		if (pct >= target) {
			return { kind: 'met' as const, due, grace };
		} else if (now < due) {
			return { kind: 'due' as const, due, grace, days: daysLeft(due, now) };
		} else if (now <= grace) {
			return { kind: 'grace' as const, due, grace, days: daysLeft(grace, now) };
		}
		return { kind: 'risk' as const, due, grace };
	});

	const latestPostByStudent = $derived.by(() => {
		const map = new SvelteMap<string, PostAssessmentStudent>();
		for (const submission of activePostSubmissions) {
			const key = studentKeyFromSubmission(submission);
			const current = map.get(key);
			const currentDate = current
				? (parseSubmissionDate(current.submission_date)?.getTime() ?? 0)
				: 0;
			const submissionDate = parseSubmissionDate(submission.submission_date)?.getTime() ?? 0;
			if (!current || submissionDate >= currentDate) {
				map.set(key, submission);
			}
		}
		return map;
	});

	const postStatusCounts = $derived.by(() => {
		const counts = { OK: 0, PEND: 0, NRC: 0, PRE: 0 };
		for (const submission of latestPostByStudent.values()) {
			const status = submission.status ?? 'PEND';
			if (status === 'OK') counts.OK += 1;
			else if (status === 'NRC') counts.NRC += 1;
			else if (status === 'PRE') counts.PRE += 1;
			else counts.PEND += 1;
		}
		return counts;
	});
	const needsPostReview = $derived(postStatusCounts.NRC > 0 || postStatusCounts.PRE > 0);
	const postReviewAlertStyle = $derived.by(() => {
		if (!needsPostReview) return null;
		if (postDeadlines.kind === 'grace') {
			return {
				icon: Hourglass,
				cls: 'border-amber-600 bg-amber-50 text-amber-800 dark:border-amber-400 dark:bg-amber-950/40 dark:text-amber-100',
				pill: daysLabel(postDeadlines.days)
					? `Grace period / ${daysLabel(postDeadlines.days)} left`
					: 'Grace period'
			};
		}
		if (postDeadlines.kind === 'risk') {
			return {
				icon: AlertTriangle,
				cls: 'border-red-600 bg-red-50 text-red-800 dark:border-red-500 dark:bg-red-950/50 dark:text-red-100',
				pill: 'Past deadline'
			};
		}
		return {
			icon: AlertTriangle,
			cls: 'border-sky-600 bg-sky-50 text-sky-800 dark:border-sky-400 dark:bg-sky-950/50 dark:text-sky-100',
			pill: 'Action needed'
		};
	});

	// Enrollment editor state
	let showEnrollmentDialog = $state(false);
	let pendingEnrollment = $state<number | null>(null);
	let savingEnrollment = $state(false);
	let showPreDetails = $state(false);
	let showPostDetails = $state(false);

	function openEnrollmentEditor() {
		pendingEnrollment = typeof course?.enrollment_count === 'number' ? course?.enrollment_count : 0;
		showEnrollmentDialog = true;
	}

	function removalStatusBadge(removed?: boolean) {
		if (removed) {
			return {
				label: 'Removed',
				explanation: null,
				className:
					'font-medium border-red-500 text-red-800 bg-red-50 dark:text-red-100 dark:border-red-400 dark:bg-red-900/40'
			};
		}
		return {
			label: 'Enrolled',
			explanation: null,
			className:
				'font-medium border-emerald-500 text-emerald-800 bg-emerald-50 dark:text-emerald-100 dark:border-emerald-400 dark:bg-emerald-900/40'
		};
	}

	function rosterStatusBadge(student: StudentRosterEntry) {
		const base = removalStatusBadge(student.removed);
		const severity: Record<string, number> = { NRC: 3, PRE: 2, PEND: 1, OK: 0 };
		let worstStatus: PostAssessmentStudent['status'] | undefined = undefined;
		let worstScore = -1;
		for (const submission of student.post_submissions || []) {
			const status = submission.status ?? 'PEND';
			const score = severity[status] ?? -1;
			if (score > worstScore) {
				worstScore = score;
				worstStatus = status;
			}
		}

		if (!worstStatus || worstScore < 0) return base;

		const postBadge = postStatusBadge(worstStatus);
		return postBadge
			? {
					label: postBadge.label,
					className: `${postBadge.className} font-medium`,
					explanation: postBadge.explanation
				}
			: base;
	}

	function postStatusBadge(status?: PostAssessmentStudent['status']) {
		switch (status) {
			case 'OK':
				return {
					label: 'Confirmed',
					explanation: null,
					className:
						'border-emerald-500 text-emerald-800 bg-emerald-50 dark:text-emerald-100 dark:border-emerald-400 dark:bg-emerald-900/40'
				};
			case 'NRC':
				return {
					label: 'No Student Record',
					explanation:
						'We were unable to match the student to a pre-assessment submission. Please ask the student to complete the pre-assessment using your course link.',
					className:
						'border-red-500 text-red-800 bg-red-50 dark:text-red-100 dark:border-red-400 dark:bg-red-900/40'
				};
			case 'PRE':
				return {
					label: 'No Pre-Assessment',
					explanation:
						'We matched this student because they completed a pre-assessment for another course, but still need their pre-assessment submission for this course. Ask the student to complete the pre-assessment using your course link. They will not have to retake the assignment questions.',
					className:
						'border-amber-500 text-amber-800 bg-amber-50 dark:text-amber-100 dark:border-amber-400 dark:bg-amber-900/40'
				};
			case 'PEND':
			default:
				return {
					label: 'Pending Review',
					explanation:
						'We were unable to automatically match the student to a pre-assessment submission. This might indicate that the student used a new email address, or that there was a technical issue. Our team will manually review and follow up as needed.',
					className:
						'border-sky-500 text-sky-800 bg-sky-50 dark:text-sky-100 dark:border-sky-400 dark:bg-sky-900/40'
				};
		}
	}

	async function saveEnrollment() {
		const parsed = Number(pendingEnrollment);
		if (!Number.isFinite(parsed) || parsed < 0) {
			toast.error('Please enter a valid non-negative number.');
			return;
		}
		savingEnrollment = true;
		const courseId = page.params.courseId as string;
		const res = await updateCourseEnrollment(fetch, courseId, Math.floor(parsed));
		if (res.$status && res.$status < 300) {
			// Update local store so UI reflects change immediately
			coursesStore.update((list) =>
				(list || []).map((c) =>
					c.id === (course?.id as string) ? { ...c, enrollment_count: Math.floor(parsed) } : c
				)
			);
			toast.success('Enrollment updated');
			showEnrollmentDialog = false;
		} else {
			toast.error(res?.detail?.toString() || 'Failed to update enrollment.');
		}
		savingEnrollment = false;
	}

	const deadlines = $derived.by(() => {
		const now = new SvelteDate();
		const start = toDate(course?.start_date);
		const target =
			typeof course?.completion_rate_target === 'number'
				? course?.completion_rate_target
				: undefined;
		const enrollment =
			typeof course?.enrollment_count === 'number' ? course?.enrollment_count : undefined;
		const completed =
			typeof course?.preassessment_student_count === 'number'
				? course?.preassessment_student_count
				: 0;

		if (!start || !target || !enrollment || enrollment <= 0) {
			return { kind: 'missing' as const, due: null as Date | null, grace: null as Date | null };
		}

		const pct = Math.round((completed / enrollment) * 100);
		if (pct >= target) {
			return { kind: 'met' as const, due: addDays(start, 14), grace: addDays(start, 22) };
		}

		const due = addDays(start, 15);
		const grace = addDays(start, 22);

		if (now < start) {
			return { kind: 'upcoming' as const, due, grace, days: daysLeft(due, now) };
		} else if (now <= due) {
			return { kind: 'due' as const, due, grace, days: daysLeft(due, now) };
		} else if (now <= grace) {
			return { kind: 'grace' as const, due, grace, days: daysLeft(grace, now) };
		}
		return { kind: 'risk' as const, due, grace };
	});
</script>

<div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
	<div class="flex flex-col gap-4 lg:col-span-2">
		{#if !loading && needsPostReview && postReviewAlertStyle}
			{@const AlertIcon = postReviewAlertStyle.icon}
			<Alert.Root class={`self-start ${postReviewAlertStyle.cls}`}>
				<AlertIcon />
				<Alert.Title class="line-clamp-none font-semibold tracking-normal">
					Some post-assessment submissions need review
				</Alert.Title>
				<Alert.Description class="space-y-1 text-sm">
					<p>
						Our team could not match some post-assessment submissions to enrolled students in your
						course. Please check the Student Roster for details and next steps.
					</p>
				</Alert.Description>
			</Alert.Root>
		{/if}
		{#if deadlines.kind === 'grace'}
			<Alert.Root
				class="self-start border-amber-600 bg-transparent text-amber-700 dark:border-amber-400 dark:text-amber-300"
			>
				<Hourglass />
				<Alert.Title class="line-clamp-none font-semibold tracking-normal"
					>Pre-Assessment Grace Period / {daysLabel(deadlines.days)} left</Alert.Title
				>
				<Alert.Description class="text-amber-700 dark:text-amber-300">
					<span>
						Your course has not reached the pre-assessment completion target. We're allowing you an
						extra week to reach the completion target and remain in the study.
					</span>
					<span>
						Extenuating circumstances? Email us at <a
							href="mailto:support@pingpong-hks.atlassian.net"
							class="text-nowrap text-amber-700 underline underline-offset-4 hover:text-amber-600 dark:text-amber-300 dark:hover:text-amber-500"
							>support@pingpong-hks.atlassian.net</a
						>.
					</span>
				</Alert.Description>
			</Alert.Root>
		{/if}
		{#if deadlines.kind === 'risk'}
			<Alert.Root
				class="self-start border-red-600 bg-transparent text-red-700 dark:border-red-400 dark:text-red-300"
			>
				<AlertTriangle />
				<Alert.Title class="line-clamp-none font-semibold tracking-normal"
					>Pre-Assessment Target Missed</Alert.Title
				>
				<Alert.Description class="text-red-700 dark:text-red-300">
					<span>
						Your course did not meet the pre-assessment completion target. Our team will follow up
						with you to discuss next steps.
					</span>
					<span>
						Extenuating circumstances? Email
						<a
							href="mailto:support@pingpong-hks.atlassian.net"
							class="text-nowrap text-red-700 underline underline-offset-4 hover:text-red-600 dark:text-red-300 dark:hover:text-red-400"
							>support@pingpong-hks.atlassian.net</a
						>.
					</span>
				</Alert.Description>
			</Alert.Root>
		{/if}
		{#if postDeadlines.kind === 'grace'}
			<Alert.Root
				class="self-start border-amber-600 bg-transparent text-amber-700 dark:border-amber-400 dark:text-amber-300"
			>
				<Hourglass />
				<Alert.Title class="line-clamp-none font-semibold tracking-normal"
					>Post-Assessment Grace Period / {daysLabel(postDeadlines.days)} left</Alert.Title
				>
				<Alert.Description class="text-amber-700 dark:text-amber-300">
					<span>
						Your course has not reached the post-assessment completion target. We're allowing you an
						extra week to reach the completion target and remain in the study.
					</span>
					<span>
						Extenuating circumstances? Email us at <a
							href="mailto:support@pingpong-hks.atlassian.net"
							class="text-nowrap text-amber-700 underline underline-offset-4 hover:text-amber-600 dark:text-amber-300 dark:hover:text-amber-500"
							>support@pingpong-hks.atlassian.net</a
						>.
					</span>
				</Alert.Description>
			</Alert.Root>
		{/if}
		{#if postDeadlines.kind === 'risk'}
			<Alert.Root
				class="self-start border-red-600 bg-transparent text-red-700 dark:border-red-400 dark:text-red-300"
			>
				<AlertTriangle />
				<Alert.Title class="line-clamp-none font-semibold tracking-normal"
					>Post-Assessment Target Missed</Alert.Title
				>
				<Alert.Description class="text-red-700 dark:text-red-300">
					<span>
						Your course did not meet the post-assessment completion target. Our team will follow up
						with you to discuss next steps.
					</span>
					<span>
						Extenuating circumstances? Email
						<a
							href="mailto:support@pingpong-hks.atlassian.net"
							class="text-nowrap text-red-700 underline underline-offset-4 hover:text-red-600 dark:text-red-300 dark:hover:text-red-400"
							>support@pingpong-hks.atlassian.net</a
						>.
					</span>
				</Alert.Description>
			</Alert.Root>
		{/if}
		<!-- Overview & Completion -->
		<div class="rounded-md border p-4">
			<div class="mb-3 flex items-center justify-between gap-3">
				<h2 class="text-lg font-semibold">Course Overview</h2>
				{#if course}
					<Button variant="outline" size="sm" onclick={openEnrollmentEditor}
						>Adjust Enrollment</Button
					>
				{/if}
			</div>
			{#if !course}
				<div class="space-y-2">
					<Skeleton class="h-5 w-1/3" />
					<Skeleton class="h-5 w-1/4" />
					<Skeleton class="h-5 w-1/2" />
					<Skeleton class="h-5 w-1/3" />
				</div>
			{:else}
				<div class="space-y-3 text-sm">
					<div class="grid grid-cols-1 items-center gap-2 sm:grid-cols-3">
						<div class="text-muted-foreground">Status</div>
						<div class="sm:col-span-2"><StatusBadge status={course.status || 'in_review'} /></div>
					</div>
					<div class="grid grid-cols-1 items-center gap-2 sm:grid-cols-3">
						<div class="text-muted-foreground">Randomization</div>
						<div class="sm:col-span-2">
							{#if course.randomization}<RandomizationBadge status={course.randomization} />{:else}
								<span class="text-muted-foreground">Not assigned</span>
							{/if}
						</div>
					</div>
					<div class="grid grid-cols-1 items-center gap-2 sm:grid-cols-3">
						<div class="text-muted-foreground">Start date</div>
						<div class="sm:col-span-2">
							{course.start_date
								? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(
										new SvelteDate(String(course.start_date))
									)
								: '—'}
						</div>
					</div>
					<div class="grid grid-cols-1 items-center gap-2 sm:grid-cols-3">
						<div class="text-muted-foreground">End date</div>
						<div class="sm:col-span-2">
							{course.end_date
								? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(
										new SvelteDate(String(course.end_date))
									)
								: '—'}
						</div>
					</div>
					<div class="grid grid-cols-1 items-center gap-2 sm:grid-cols-3">
						<div class="text-muted-foreground">Enrollment</div>
						<div class="sm:col-span-2">
							<div>{course.enrollment_count ?? '—'}</div>
						</div>
					</div>

					<div class="grid grid-cols-1 items-center gap-2 sm:grid-cols-3">
						<div class="text-muted-foreground">PingPong Group</div>
						<div class="sm:col-span-2">
							{#if course.pingpong_group_url}
								<UrlCopyField url={course.pingpong_group_url} />
							{:else}
								<span class="text-muted-foreground">Not assigned</span>
							{/if}
						</div>
					</div>

					<div class="grid grid-cols-1 items-center gap-2 sm:grid-cols-3">
						<div class="text-muted-foreground">Pre-assessment Form</div>
						<div class="sm:col-span-2">
							{#if course.preassessment_url}
								<UrlCopyField url={course.preassessment_url} />
							{:else}
								<span class="text-muted-foreground">Not assigned</span>
							{/if}
						</div>
					</div>
					<div class="grid grid-cols-1 items-center gap-2 sm:grid-cols-3">
						<div class="text-muted-foreground">Post-assessment Form</div>
						<div class="sm:col-span-2">
							{#if course.postassessment_url}
								<UrlCopyField url={course.postassessment_url} />
							{:else}
								<span class="text-muted-foreground">Not assigned</span>
							{/if}
						</div>
					</div>
				</div>
			{/if}
		</div>

		<div class="flex flex-col gap-3 rounded-md border p-4">
			<div class="flex items-center justify-between">
				<h2 class="text-lg font-semibold">Pre-Assessment Completion</h2>
				{#if !loading && course}
					<div class="flex items-center gap-2">
						{#if deadlines.kind === 'met'}
							<Badge
								variant="outline"
								class="!gap-2 border-emerald-600 bg-transparent text-sm text-emerald-600 [&>svg]:!size-4 [a&]:hover:bg-transparent"
							>
								<Check />
								Target met
							</Badge>
						{:else if deadlines.kind === 'due' || deadlines.kind === 'upcoming'}
							<Badge
								variant="outline"
								class="!gap-2 border-sky-600 bg-transparent text-sm text-sky-600 [&>svg]:!size-4 [a&]:hover:bg-transparent"
							>
								<Clock />
								Below target / {daysLabel(deadlines.days)} left
							</Badge>
						{:else if deadlines.kind === 'grace'}
							<Badge
								variant="outline"
								class="!gap-2 border-amber-600 bg-transparent text-sm text-amber-700 dark:border-amber-400 dark:text-amber-300 [&>svg]:!size-4 [a&]:hover:bg-transparent"
							>
								<Hourglass />
								Below target / Grace period: {daysLabel(deadlines.days)} left
							</Badge>
						{:else if deadlines.kind === 'risk'}
							<Badge
								variant="outline"
								class="!gap-2 border-red-600 bg-transparent text-sm text-red-600 [&>svg]:!size-4 [a&]:hover:bg-transparent"
							>
								<AlertTriangle />
								Below target / Past deadline
							</Badge>
						{/if}
						<Button variant="outline" size="sm" onclick={() => (showPreDetails = !showPreDetails)}>
							{showPreDetails ? 'Hide details' : 'Show details'}
						</Button>
					</div>
				{/if}
			</div>
			{#if loading || !course}
				<Skeleton class="h-4 w-full" />
				<div class="mt-2 flex flex-row items-center gap-2 text-sm">
					<Skeleton class="h-6 w-24" />
					<span>students</span>
				</div>
			{:else if showPreDetails}
				<div
					class="space-y-3"
					in:slide={{ duration: 220, easing: quintOut }}
					out:slide={{ duration: 160, easing: quintOut }}
				>
					<Progress
						value={completionRate}
						target={completionRateTarget}
						max={100}
						class="h-4"
						showIndicators
						textClass="text-sm"
					/>
					<div class="flex flex-row items-center gap-2 text-sm">
						<span class="text-2xl font-bold">{preAssessmentStudentCount}/{enrollmentCount}</span>
						<span>students</span>
					</div>
					{#if preAssessmentStudentCount && preAssessmentStudentCount < activePreSubmissions.length}
						<Alert.Root class="self-start">
							<Info />
							<Alert.Title class="line-clamp-none tracking-normal"
								>Student count lower than submission count</Alert.Title
							>
							<Alert.Description>
								<p>
									Some students have submitted the pre-assessment multiple times. We group
									submissions by email address. Email <a
										href="mailto:support@pingpong-hks.atlassian.net"
										class="text-nowrap text-primary underline underline-offset-4 hover:text-primary/80"
										>support@pingpong-hks.atlassian.net</a
									> if you have any questions.
								</p>
							</Alert.Description>
						</Alert.Root>
					{/if}
					{#if !loading && course}
						<Alert.Root class="self-start">
							<Info />
							<Alert.Title class="line-clamp-none tracking-normal"
								>Need to adjust your enrollment count?</Alert.Title
							>
							<Alert.Description>
								<p>
									We use your enrollment count to calculate completion rates. Use the <i
										>Adjust Enrollment</i
									> button above to update your enrollment count.
								</p>
							</Alert.Description>
						</Alert.Root>
					{/if}
				</div>
			{/if}
		</div>

		<div class="flex flex-col gap-3 rounded-md border p-4">
			<div class="flex items-center justify-between">
				<h2 class="text-lg font-semibold">Post-Assessment Completion</h2>
				{#if !loading && course}
					<div class="flex items-center gap-2">
						{#if postDeadlines.kind === 'upcoming'}
							<Badge
								variant="outline"
								class="!gap-2 border-muted-foreground bg-transparent text-sm text-muted-foreground [&>svg]:!size-4 [a&]:hover:bg-transparent"
							>
								<Calendar />
								Last 2 weeks of class
							</Badge>
						{:else if postDeadlines.kind === 'met'}
							<Badge
								variant="outline"
								class="!gap-2 border-emerald-600 bg-transparent text-sm text-emerald-600 [&>svg]:!size-4 [a&]:hover:bg-transparent"
							>
								<Check />
								Target met
							</Badge>
						{:else if postDeadlines.kind === 'due'}
							<Badge
								variant="outline"
								class="!gap-2 border-sky-600 bg-transparent text-sm text-sky-600 [&>svg]:!size-4 [a&]:hover:bg-transparent"
							>
								<Clock />
								Below target / {daysLabel(postDeadlines.days)} left
							</Badge>
						{:else if postDeadlines.kind === 'grace'}
							<Badge
								variant="outline"
								class="!gap-2 border-amber-600 bg-transparent text-sm text-amber-700 dark:border-amber-400 dark:text-amber-300 [&>svg]:!size-4 [a&]:hover:bg-transparent"
							>
								<Hourglass />
								Below target / Grace period: {daysLabel(postDeadlines.days)} left
							</Badge>
						{:else if postDeadlines.kind === 'risk'}
							<Badge
								variant="outline"
								class="!gap-2 border-red-600 bg-transparent text-sm text-red-600 [&>svg]:!size-4 [a&]:hover:bg-transparent"
							>
								<AlertTriangle />
								Below target / Past deadline
							</Badge>
						{/if}
						{#if postDeadlines.kind !== 'upcoming'}
							<Button
								variant="outline"
								size="sm"
								onclick={() => (showPostDetails = !showPostDetails)}
							>
								{showPostDetails ? 'Hide details' : 'Show details'}
							</Button>
						{/if}
					</div>
				{/if}
			</div>
			{#if loading || !course}
				<Skeleton class="h-4 w-full" />
				<div class="mt-2 flex flex-row items-center gap-2 text-sm">
					<Skeleton class="h-6 w-24" />
					<span>students</span>
				</div>
			{:else if showPostDetails}
				<div
					class="space-y-3"
					in:slide={{ duration: 220, easing: quintOut }}
					out:slide={{ duration: 160, easing: quintOut }}
				>
					<Progress
						value={postCompletionRate}
						target={completionRateTarget}
						max={100}
						class="h-4"
						showIndicators
						textClass="text-sm"
					/>
					<div class="flex flex-row items-center gap-2 text-sm">
						<span class="text-2xl font-bold"
							>{postAssessmentStudentCount ?? 0}/{enrollmentCount ?? '—'}</span
						>
						<span>students</span>
					</div>

					{#if activePostSubmissions.length === 0}
						<div class="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
							No post-assessment submissions yet.
						</div>
					{:else}
						<div class="grid grid-cols-2 gap-2 md:grid-cols-4">
							<div class="flex flex-row gap-1">
								<Badge
									variant="outline"
									class="!gap-2 border-emerald-600 bg-transparent text-emerald-700 dark:border-emerald-500 dark:text-emerald-200 [&>svg]:!size-4 [a&]:hover:bg-transparent"
								>
									<CheckCircle class="size-4" />
									Confirmed ({postStatusCounts.OK})
								</Badge>
							</div>
							<div class="flex flex-row gap-1.5">
								<Badge
									variant="outline"
									class="!gap-2 border-sky-600 bg-transparent text-sky-700 dark:border-sky-400 dark:text-sky-200 [&>svg]:!size-4 [a&]:hover:bg-transparent"
								>
									<Clock class="size-4" />
									Pending Review ({postStatusCounts.PEND})
								</Badge>
								<Tooltip.Provider delayDuration={50}>
									<Tooltip.Root>
										<Tooltip.Trigger>
											<CircleHelp size="16" class="text-muted-foreground" />
										</Tooltip.Trigger>
										<Tooltip.Content side="top" sideOffset={2} class="w-md">
											<span class="w-full text-sm"
												>We were unable to automatically match the student to a pre-assessment
												submission. This might indicate that the student used a new email address,
												or that there was a technical issue. Our team will manually review and
												follow up as needed.</span
											>
										</Tooltip.Content>
									</Tooltip.Root>
								</Tooltip.Provider>
							</div>
							<div class="flex flex-row gap-1.5">
								<Badge
									variant="outline"
									class="!gap-2 border-amber-600 bg-transparent text-amber-700 dark:border-amber-400 dark:text-amber-200 [&>svg]:!size-4 [a&]:hover:bg-transparent"
								>
									<Hourglass class="size-4" />
									No Pre-Assessment ({postStatusCounts.PRE})
								</Badge>
								<Tooltip.Provider delayDuration={50}>
									<Tooltip.Root>
										<Tooltip.Trigger>
											<CircleHelp size="16" class="text-muted-foreground" />
										</Tooltip.Trigger>
										<Tooltip.Content side="top" sideOffset={2} class="w-md">
											<span class="w-full text-sm"
												>We matched this student because they completed a pre-assessment for another
												course, but still need their pre-assessment submission for this course. Ask
												the student to complete the pre-assessment using your course link. They will
												not have to retake the assignment questions.</span
											>
										</Tooltip.Content>
									</Tooltip.Root>
								</Tooltip.Provider>
							</div>
							<div class="flex flex-row gap-1.5">
								<Badge
									variant="outline"
									class="!gap-2 border-red-600 bg-transparent text-red-700 dark:border-red-500 dark:text-red-200 [&>svg]:!size-4 [a&]:hover:bg-transparent"
								>
									<AlertTriangle class="size-4" />
									No Student Record ({postStatusCounts.NRC})
								</Badge>
								<Tooltip.Provider delayDuration={50}>
									<Tooltip.Root>
										<Tooltip.Trigger>
											<CircleHelp size="16" class="text-muted-foreground" />
										</Tooltip.Trigger>
										<Tooltip.Content side="top" sideOffset={2} class="w-md">
											<span class="w-full text-sm"
												>We were unable to match the student to a pre-assessment submission. Please
												ask the student to complete the pre-assessment using your course link.</span
											>
										</Tooltip.Content>
									</Tooltip.Root>
								</Tooltip.Provider>
							</div>
						</div>
						{#if postAssessmentStudentCount && postAssessmentStudentCount < activePostSubmissions.length}
							<Alert.Root class="self-start">
								<Info />
								<Alert.Title class="line-clamp-none tracking-normal"
									>Student count lower than submission count</Alert.Title
								>
								<Alert.Description>
									<p>
										Some students have submitted the post-assessment multiple times. We group
										submissions by email address. Email <a
											href="mailto:support@pingpong-hks.atlassian.net"
											class="text-nowrap text-primary underline underline-offset-4 hover:text-primary/80"
											>support@pingpong-hks.atlassian.net</a
										> if you have any questions.
									</p>
								</Alert.Description>
							</Alert.Root>
						{/if}
						{#if !loading && course}
							<Alert.Root class="self-start">
								<Info />
								<Alert.Title class="line-clamp-none tracking-normal"
									>Need to adjust your enrollment count?</Alert.Title
								>
								<Alert.Description>
									<p>
										We use your enrollment count to calculate completion rates. Use the <i
											>Adjust Enrollment</i
										> button above to update your enrollment count.
									</p>
								</Alert.Description>
							</Alert.Root>
						{/if}
					{/if}
				</div>
			{/if}
		</div>

		<!-- Student roster -->
		<div class="flex flex-col gap-2">
			<div class="flex items-center justify-between gap-2">
				<h2 class="text-lg font-semibold">Student Roster</h2>
				{#if !loading}
					<div class="text-sm text-muted-foreground">
						{activeRoster.length}
						{activeRoster.length === 1 ? 'enrolled student' : 'enrolled students'}
					</div>
				{/if}
			</div>
			{#if loading}
				<div class="space-y-2">
					<Skeleton class="h-8 w-full" />
					<Skeleton class="h-8 w-full" />
					<Skeleton class="h-8 w-full" />
					<Skeleton class="h-8 w-full" />
				</div>
			{:else if studentRoster.length === 0}
				<div class="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
					No students yet.
				</div>
			{:else}
				<div class="grid items-start gap-4">
					<div class="flex max-h-[50vh] flex-col rounded-md border">
						<div class="flex items-center justify-between border-b px-4 py-3">
							<h3 class="text-base font-semibold">Enrolled students</h3>
							<span class="text-sm text-muted-foreground">{activeRoster.length}</span>
						</div>
						{#if !activeRoster.length}
							<div class="p-4 text-sm text-muted-foreground">No enrolled students.</div>
						{:else}
							<div class="flex-1 overflow-auto">
								<Table.Root class="table-fixed">
									<colgroup>
										<col class="w-12" />
										<col />
										<col />
										<col class="w-52" />
										<col class="w-32" />
										<col class="w-32" />
										<col class="w-12" />
									</colgroup>
									<Table.Header>
										<Table.Row>
											<Table.Head class="w-12">#</Table.Head>
											<Table.Head>Student</Table.Head>
											<Table.Head>Email</Table.Head>
											<Table.Head class="w-28">Status</Table.Head>
											<Table.Head class="text-left">Pre</Table.Head>
											<Table.Head class="text-left">Post</Table.Head>
											<Table.Head class="w-12 text-right"></Table.Head>
										</Table.Row>
									</Table.Header>
									<Table.Body>
										{#each activeRoster as student, index (student.id)}
											{@const statusBadgeEl = rosterStatusBadge(student)}
											<Table.Row>
												<Table.Cell class="font-medium">{index + 1}</Table.Cell>
												<Table.Cell class="max-w-xs truncate">{studentName(student)}</Table.Cell>
												<Table.Cell class="max-w-xs truncate">
													{#if student.email}
														{student.email}
													{:else}
														<span class="text-muted-foreground">No email</span>
													{/if}
												</Table.Cell>
												<Table.Cell class="w-52">
													<div class="flex h-full items-center gap-2 py-1">
														<Badge variant="outline" class={statusBadgeEl.className}>
															{statusBadgeEl.label === 'Confirmed'
																? 'Enrolled'
																: statusBadgeEl.label}
														</Badge>
														{#if statusBadgeEl.explanation}
															<Tooltip.Provider delayDuration={50}>
																<Tooltip.Root>
																	<Tooltip.Trigger>
																		<CircleHelp size="16" class="text-muted-foreground" />
																	</Tooltip.Trigger>
																	<Tooltip.Content side="top" sideOffset={2} class="w-md">
																		<span class="w-full text-sm">{statusBadgeEl.explanation}</span>
																	</Tooltip.Content>
																</Tooltip.Root>
															</Tooltip.Provider>
														{/if}
													</div>
												</Table.Cell>
												<Table.Cell class="text-left">
													{#if student.pre_submissions.length}
														<button
															type="button"
															class="inline-flex items-center justify-end gap-2 text-sm font-medium text-primary hover:text-primary/80"
															onclick={() => togglePreSubmissions(student.id)}
														>
															<CheckCircle class="size-4 text-emerald-500" />
															<span>{student.pre_submissions.length}</span>
															{#if preExpandedStudents.has(student.id)}
																<ChevronDown class="size-4" />
															{:else}
																<ChevronRight class="size-4" />
															{/if}
														</button>
													{:else}
														<div
															class="flex items-center justify-start gap-2 text-sm text-muted-foreground"
														>
															<CircleOff class="size-4" />
														</div>
													{/if}
												</Table.Cell>
												<Table.Cell class="text-left">
													{#if student.post_submissions.length}
														<button
															type="button"
															class="inline-flex items-center justify-end gap-2 text-sm font-medium text-primary hover:text-primary/80"
															onclick={() => togglePostSubmissions(student.id)}
														>
															<CheckCircle class="size-4 text-emerald-500" />
															<span>{student.post_submissions.length}</span>
															{#if postExpandedStudents.has(student.id)}
																<ChevronDown class="size-4" />
															{:else}
																<ChevronRight class="size-4" />
															{/if}
														</button>
													{:else}
														<div
															class="flex items-center justify-start gap-2 text-sm text-muted-foreground"
														>
															<CircleOff class="size-4" />
														</div>
													{/if}
												</Table.Cell>
												<Table.Cell class="text-right">
													<button
														type="button"
														class="inline-flex items-center justify-center rounded border border-transparent p-1 text-muted-foreground hover:text-destructive focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:outline-none"
														aria-label="Remove student"
														onclick={() => openRemovalDialog(student)}
													>
														<Trash class="size-4" />
													</button>
												</Table.Cell>
											</Table.Row>
											{#if student.pre_submissions.length && preExpandedStudents.has(student.id)}
												{#each student.pre_submissions as submission, submissionIndex (submission.id)}
													<Table.Row class="bg-muted/40">
														<Table.Cell class="text-xs text-muted-foreground"
															>↳ {submissionIndex + 1}</Table.Cell
														>
														<Table.Cell class="max-w-xs truncate text-xs">
															{submissionDisplayName(submission)}
														</Table.Cell>
														<Table.Cell class="max-w-xs truncate text-xs">
															{submission.email ?? '—'}
														</Table.Cell>
														<Table.Cell class="text-xs text-muted-foreground"></Table.Cell>
														<Table.Cell class="text-right text-xs">
															{formatSubmissionDate(submission.submission_date) || '—'}
														</Table.Cell>
														<Table.Cell class="text-left text-xs"></Table.Cell>
														<Table.Cell />
													</Table.Row>
												{/each}
											{/if}
											{#if student.post_submissions.length && postExpandedStudents.has(student.id)}
												{#each student.post_submissions as submission, submissionIndex (submission.id)}
													<Table.Row class="bg-muted/30">
														<Table.Cell class="text-xs text-muted-foreground"
															>↳ {submissionIndex + 1}</Table.Cell
														>
														<Table.Cell class="max-w-xs truncate text-xs">
															{submissionDisplayName(submission)}
														</Table.Cell>
														<Table.Cell class="max-w-xs truncate text-xs">
															{submission.email ?? '—'}
														</Table.Cell>
														<Table.Cell class="text-xs text-muted-foreground">
															{#if postStatusBadge(submission.status)}
																<span
																	class={`inline-flex items-center rounded border px-2 py-0.5 text-[11px] leading-tight font-medium ${postStatusBadge(submission.status).className}`}
																>
																	{postStatusBadge(submission.status).label}
																</span>
															{/if}
														</Table.Cell>
														<Table.Cell class="text-right text-xs"></Table.Cell>
														<Table.Cell class="text-right text-xs">
															{formatSubmissionDate(submission.submission_date) || '—'}
														</Table.Cell>
														<Table.Cell />
													</Table.Row>
												{/each}
											{/if}
										{/each}
									</Table.Body>
								</Table.Root>
							</div>
						{/if}
					</div>

					<div class="flex max-h-[50vh] flex-col rounded-md border">
						<div class="flex items-center justify-between border-b px-4 py-3">
							<h3 class="text-base font-semibold">Removed students</h3>
							<span class="text-sm text-muted-foreground">{removedRoster.length}</span>
						</div>
						{#if !removedRoster.length}
							<div class="p-4 text-sm text-muted-foreground">No removed students.</div>
						{:else}
							<div class="flex-1 overflow-auto">
								<Table.Root class="table-fixed">
									<colgroup>
										<col class="w-12" />
										<col />
										<col />
										<col class="w-52" />
										<col class="w-32" />
										<col class="w-32" />
										<col class="w-12" />
									</colgroup>
									<Table.Header>
										<Table.Row>
											<Table.Head class="w-12"></Table.Head>
											<Table.Head>Student</Table.Head>
											<Table.Head>Email</Table.Head>
											<Table.Head class="w-28">Status</Table.Head>
											<Table.Head class="text-left">Pre</Table.Head>
											<Table.Head class="text-left">Post</Table.Head>
											<Table.Head class="w-12" />
										</Table.Row>
									</Table.Header>
									<Table.Body>
										{#each removedRoster as student (student.id)}
											<Table.Row>
												<Table.Cell class="font-medium text-muted-foreground"></Table.Cell>
												<Table.Cell class="max-w-xs truncate">{studentName(student)}</Table.Cell>
												<Table.Cell class="max-w-xs truncate">
													{#if student.email}
														{student.email}
													{:else}
														<span class="text-muted-foreground">No email</span>
													{/if}
												</Table.Cell>
												<Table.Cell class="w-36">
													<Badge
														variant="outline"
														class={removalStatusBadge(student.removed).className}
													>
														{removalStatusBadge(student.removed).label}
													</Badge>
												</Table.Cell>
												<Table.Cell class="text-left">
													{#if student.pre_submissions.length}
														<button
															type="button"
															class="inline-flex items-center justify-end gap-2 text-sm font-medium text-primary hover:text-primary/80"
															onclick={() => togglePreSubmissions(student.id)}
														>
															<CheckCircle class="size-4 text-emerald-500" />
															<span>{student.pre_submissions.length}</span>
															{#if preExpandedStudents.has(student.id)}
																<ChevronDown class="size-4" />
															{:else}
																<ChevronRight class="size-4" />
															{/if}
														</button>
													{:else}
														<div
															class="flex items-center justify-end gap-2 text-sm text-muted-foreground"
														>
															<CircleOff class="size-4" />
														</div>
													{/if}
												</Table.Cell>
												<Table.Cell class="text-left">
													{#if student.post_submissions.length}
														<button
															type="button"
															class="inline-flex items-center justify-end gap-2 text-sm font-medium text-primary hover:text-primary/80"
															onclick={() => togglePostSubmissions(student.id)}
														>
															<CheckCircle class="size-4 text-emerald-500" />
															<span>{student.post_submissions.length}</span>
															{#if postExpandedStudents.has(student.id)}
																<ChevronDown class="size-4" />
															{:else}
																<ChevronRight class="size-4" />
															{/if}
														</button>
													{:else}
														<div
															class="flex items-center justify-start gap-2 text-sm text-muted-foreground"
														>
															<CircleOff class="size-4" />
														</div>
													{/if}
												</Table.Cell>
												<Table.Cell />
											</Table.Row>
											{#if student.pre_submissions.length && preExpandedStudents.has(student.id)}
												{#each student.pre_submissions as submission, submissionIndex (submission.id)}
													<Table.Row class="bg-muted/40">
														<Table.Cell class="text-xs text-muted-foreground"
															>↳ {submissionIndex + 1}</Table.Cell
														>
														<Table.Cell class="max-w-xs truncate text-xs">
															{submissionDisplayName(submission)}
														</Table.Cell>
														<Table.Cell class="max-w-xs truncate text-xs">
															{submission.email ?? '—'}
														</Table.Cell>
														<Table.Cell class="text-xs text-muted-foreground"></Table.Cell>
														<Table.Cell class="text-right text-xs">
															{formatSubmissionDate(submission.submission_date) || '—'}
														</Table.Cell>
														<Table.Cell class="text-right text-xs"></Table.Cell>
														<Table.Cell />
													</Table.Row>
												{/each}
											{/if}
											{#if student.post_submissions.length && postExpandedStudents.has(student.id)}
												{#each student.post_submissions as submission, submissionIndex (submission.id)}
													<Table.Row class="bg-muted/30">
														<Table.Cell class="text-xs text-muted-foreground"
															>↳ {submissionIndex + 1}</Table.Cell
														>
														<Table.Cell class="max-w-xs truncate text-xs">
															{submissionDisplayName(submission)}
														</Table.Cell>
														<Table.Cell class="max-w-xs truncate text-xs">
															{submission.email ?? '—'}
														</Table.Cell>
														<Table.Cell class="text-xs text-muted-foreground">
															{#if postStatusBadge(submission.status)}
																<span
																	class={`inline-flex items-center rounded border px-2 py-0.5 text-[11px] leading-tight font-medium ${postStatusBadge(submission.status).className}`}
																>
																	{postStatusBadge(submission.status).label}
																</span>
															{/if}
														</Table.Cell>
														<Table.Cell class="text-right text-xs"></Table.Cell>
														<Table.Cell class="text-right text-xs">
															{formatSubmissionDate(submission.submission_date) || '—'}
														</Table.Cell>
														<Table.Cell />
													</Table.Row>
												{/each}
											{/if}
										{/each}
									</Table.Body>
								</Table.Root>
							</div>
						{/if}
					</div>
				</div>
			{/if}
		</div>
	</div>
	<div class="lg:col-span-1">
		<CourseTimeline course={course as Course} />
	</div>
</div>

<!-- Removal Dialog -->
<Dialog.Root bind:open={showRemovalDialog}>
	<Dialog.Content>
		<Dialog.Header>
			<Dialog.Title>Remove student</Dialog.Title>
			<Dialog.Description>
				{#if isTreatmentCourse}
					This will remove the student from the roster and the course's PingPong group.
				{:else}
					This will remove the student from the roster.
				{/if}
				A confirmation will be sent to your email.
			</Dialog.Description>
		</Dialog.Header>
		{#if confirmingStudent}
			<div class="space-y-4 py-2">
				<div class="rounded-md border p-3 text-sm">
					<div class="font-medium">{studentName(confirmingStudent)}</div>
					<div class="text-muted-foreground">{confirmingStudent.email || 'No email available'}</div>
				</div>
				<div class="space-y-2 text-sm">
					<label class="block text-muted-foreground" for="removal-confirmation">
						Type
						<strong class="text-foreground">delete</strong>
						to proceed.
					</label>
					<Input
						id="removal-confirmation"
						placeholder="delete"
						bind:value={confirmationValue}
						disabled={deletingStudent}
					/>
				</div>
			</div>
		{/if}
		<Dialog.Footer>
			<Button variant="outline" onclick={closeRemovalDialog} disabled={deletingStudent}
				>Cancel</Button
			>
			<Button
				variant="destructive"
				onclick={submitRemovalRequest}
				disabled={!canConfirmRemoval || deletingStudent}
			>
				{#if deletingStudent}Submitting...{:else}Remove student{/if}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>

<!-- Enrollment Dialog -->
<Dialog.Root bind:open={showEnrollmentDialog}>
	<Dialog.Content>
		<Dialog.Header>
			<Dialog.Title>Adjust Enrollment</Dialog.Title>
			<Dialog.Description>
				Update the expected number of enrolled students for this course. This number is used to
				calculate completion rates.
			</Dialog.Description>
		</Dialog.Header>
		<div class="grid gap-4 py-2">
			<div class="grid grid-cols-4 items-center gap-4">
				<label for="enrollment-input" class="text-right text-sm text-muted-foreground"
					>Students</label
				>
				<div class="col-span-3">
					<Input id="enrollment-input" type="number" min="0" bind:value={pendingEnrollment} />
				</div>
			</div>
		</div>
		<Dialog.Footer>
			<Button
				variant="outline"
				onclick={() => (showEnrollmentDialog = false)}
				disabled={savingEnrollment}>Cancel</Button
			>
			<Button onclick={saveEnrollment} disabled={savingEnrollment}>
				{#if savingEnrollment}Saving...{:else}Save{/if}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>

export type PreAssessmentStudent = {
	id: string;
	first_name?: string;
	last_name?: string;
	email?: string;
	submission_date?: string;
	student_id?: string | null;
	class_id?: string | null;
	removed?: boolean;
};

export type PostAssessmentStudent = {
	id: string;
	name?: string;
	email?: string;
	submission_date?: string;
	student_id?: string | null;
	class_id?: string | null;
	status?: 'OK' | 'PEND' | 'NRC' | 'PRE' | null;
	removed?: boolean;
};

export type AssessmentStudents = {
	pre_assessment_submissions: PreAssessmentStudent[];
	post_assessment_submissions: PostAssessmentStudent[];
};

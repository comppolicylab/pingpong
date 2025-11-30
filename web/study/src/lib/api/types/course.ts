export type Course = {
	id: string;
	name?: string;
	status?: 'in_review' | 'accepted' | 'rejected' | 'withdrawn';
	randomization?: 'control' | 'treatment';
	start_date?: string;
	end_date?: string;
	enrollment_count?: number;
	completion_rate_target?: number;
	preassessment_url?: string;
	postassessment_url?: string;
	pingpong_group_url?: string;
	preassessment_student_count?: number;
	postassessment_student_count?: number;
};

export type Courses = {
	courses: Course[];
};

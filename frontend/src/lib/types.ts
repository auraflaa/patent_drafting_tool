// Shapes returned by the FastAPI backend.
//
// Entity identifiers are Firestore document IDs (opaque strings). The only
// numeric IDs left are the role/permission catalog entries, which are
// code-defined constants and never stored as document IDs.

export interface UserOut {
  id: string;
  email: string;
  full_name: string;
  phone_number: string | null;
  profile_picture: string | null;
  designation: string | null;
  organization: string | null;
  account_status: "Pending" | "Approved" | "Rejected" | "Suspended";
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  roles: string[];
}

export interface MeResponse {
  user: UserOut;
  permissions: string[];
}

export interface PendingUserOut {
  id: string;
  email: string;
  full_name: string;
  organization: string | null;
  created_at: string;
}

export interface RoleOut {
  /** Catalog constant — numeric by design (see ADR-002). */
  id: number;
  role_name: string;
  role_code: string;
  is_system_role: boolean;
}

export interface PermissionOut {
  /** Catalog constant — numeric by design (see ADR-002). */
  id: number;
  permission_name: string;
  permission_code: string;
  module_name: string | null;
  action: string | null;
}

export interface RbacMatrixResponse {
  roles: RoleOut[];
  permissions: PermissionOut[];
  grants: { role_id: number; permission_id: number }[];
}

export interface UserAdminOut {
  id: string;
  email: string;
  full_name: string;
  account_status: string;
  is_active: boolean;
  roles: string[];
  created_at: string;
}

export const ALL_ROLE_CODES = ["SUPER_ADMIN", "ADMIN", "PATENT_AGENT", "INNOVATOR"] as const;
export type RoleCode = (typeof ALL_ROLE_CODES)[number];

/** Where each role lands after login. */
export const ROLE_HOME: Record<string, string> = {
  SUPER_ADMIN: "/super-admin",
  ADMIN: "/admin",
  PATENT_AGENT: "/agent",
  INNOVATOR: "/innovator",
};

// ---------------------------------------------------------------------------
// Teams
// ---------------------------------------------------------------------------

export interface TeamOut {
  id: string;
  team_name: string;
  team_status: string;
  created_by: string | null;
  created_at: string;
  member_count: number;
  patent_count: number;
}

export interface TeamMemberOut {
  id: string;
  user_id: string;
  email: string;
  full_name: string;
  membership_status: string | null;
  added_by: string | null;
}

export interface TeamDetailOut extends TeamOut {
  members: TeamMemberOut[];
}

// ---------------------------------------------------------------------------
// Patent Applications
// ---------------------------------------------------------------------------

export interface PatentOut {
  id: string;
  team_id: string;
  invention_title: string;
  application_status: string;
  assigned_patent_agent_id: string | null;
  ai_status: string | null;
  questionnaire_status: string | null;
  document_status: string | null;
  filing_status: string | null;
  official_application_number: string | null;
  filing_date: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface AvailableAgentOut {
  id: string;
  full_name: string;
  email: string;
  active_assignment_count: number;
}

// ---------------------------------------------------------------------------
// Basic Information: Applicants & Inventors
// ---------------------------------------------------------------------------

export const APPLICANT_TYPES = ["Individual", "Startup", "Company", "University"] as const;
export type ApplicantType = (typeof APPLICANT_TYPES)[number];

export interface ApplicantOut {
  id: string;
  patent_application_id: string;
  applicant_type: string;
  full_name_or_org_name: string;
  address: string | null;
  country: string | null;
  postal_code: string | null;
  email: string | null;
  phone: string | null;
  is_primary: boolean;
  display_order: number;
}

export interface ApplicantInput {
  applicant_type: ApplicantType;
  full_name_or_org_name: string;
  address: string;
  country: string;
  postal_code: string;
  email: string;
  phone: string;
  is_primary: boolean;
}

export interface InventorOut {
  id: string;
  patent_application_id: string;
  user_id: string | null;
  full_name: string;
  address: string | null;
  country: string | null;
  postal_code: string | null;
  email: string | null;
  phone: string | null;
  inventor_order: number;
}

export interface InventorInput {
  full_name: string;
  address: string;
  country: string;
  postal_code: string;
  email: string;
  phone: string;
}

// ---------------------------------------------------------------------------
// Questionnaire
// ---------------------------------------------------------------------------

export const INVENTION_TYPES = ["Software", "Mechanical", "Electronics", "Biotech", "Chemistry"] as const;
export type InventionType = (typeof INVENTION_TYPES)[number];

/** Per-type guidance driving the Technical Details branching (frontend-only —
 * the stored questionnaire keeps a single shared `technical_description` field). */
export const TECHNICAL_DETAILS_GUIDANCE: Record<InventionType, { label: string; placeholder: string }> = {
  Software: {
    label: "Technical Description — Architecture & Implementation",
    placeholder:
      "Describe the algorithm, system architecture, data flow, and key modules. What makes the implementation technically novel?",
  },
  Mechanical: {
    label: "Technical Description — Structure & Mechanism",
    placeholder:
      "Describe the physical components, materials, assembly, and how the mechanism operates. Include dimensions or tolerances if relevant.",
  },
  Electronics: {
    label: "Technical Description — Circuit & Signal Design",
    placeholder:
      "Describe the circuit design, key components, signal flow, and any control logic. Note any novel component arrangement.",
  },
  Biotech: {
    label: "Technical Description — Biological Materials & Process",
    placeholder:
      "Describe the biological materials, sequences, organisms, or processes involved, and the experimental method used to achieve the result.",
  },
  Chemistry: {
    label: "Technical Description — Composition & Reaction",
    placeholder:
      "Describe the chemical composition, formulation, synthesis, or reaction process, including key reagents and conditions.",
  },
};

export interface QuestionnaireOut {
  id: string;
  patent_application_id: string;
  questionnaire_status: "Not Started" | "In Progress" | "Completed" | null;
  completion_percentage: string | null;
  invention_type: InventionType | null;
  problem_statement: string | null;
  proposed_solution: string | null;
  novelty_description: string | null;
  technical_description: string | null;
  advantages: string | null;
  prior_art: string | null;
  keywords: string | null;
  has_existing_drawings: boolean | null;
  invention_keyword: string | null;
  title_keyword: string | null;
  problem_keyword: string | null;
  claim_keyword: string | null;
  data1: string | null;
  data2: string | null;
  field: string | null;
  domain: string | null;
  area: string | null;
  one_line_about_field: string | null;
  two_lines_about_domain: string | null;
  three_lines_about_area: string | null;
  four_lines_about_problem: string | null;
  four_lines_about_solution: string | null;
  advantage1: string | null;
  advantage2: string | null;
  exemplary_scenario: string | null;
  detailed_exemplary_scenario: string | null;
  best_working_method: string | null;
  created_at: string;
  updated_at: string;
}

export interface QuestionnaireUpdateInput {
  invention_type?: InventionType | null;
  problem_statement?: string | null;
  proposed_solution?: string | null;
  novelty_description?: string | null;
  technical_description?: string | null;
  advantages?: string | null;
  prior_art?: string | null;
  keywords?: string | null;
  has_existing_drawings?: boolean | null;
  invention_keyword?: string | null;
  title_keyword?: string | null;
  problem_keyword?: string | null;
  claim_keyword?: string | null;
  data1?: string | null;
  data2?: string | null;
  field?: string | null;
  domain?: string | null;
  area?: string | null;
  one_line_about_field?: string | null;
  two_lines_about_domain?: string | null;
  three_lines_about_area?: string | null;
  four_lines_about_problem?: string | null;
  four_lines_about_solution?: string | null;
  advantage1?: string | null;
  advantage2?: string | null;
  exemplary_scenario?: string | null;
  detailed_exemplary_scenario?: string | null;
  best_working_method?: string | null;
}

export interface QuestionnaireVersionOut {
  id: string;
  questionnaire_id: string;
  patent_application_id: string;
  version_number: number;
  version_status: string | null;
  invention_type: string | null;
  problem_statement: string | null;
  proposed_solution: string | null;
  novelty_description: string | null;
  technical_description: string | null;
  advantages: string | null;
  prior_art: string | null;
  keywords: string | null;
  invention_keyword: string | null;
  title_keyword: string | null;
  problem_keyword: string | null;
  claim_keyword: string | null;
  data1: string | null;
  data2: string | null;
  field: string | null;
  domain: string | null;
  area: string | null;
  one_line_about_field: string | null;
  two_lines_about_domain: string | null;
  three_lines_about_area: string | null;
  four_lines_about_problem: string | null;
  four_lines_about_solution: string | null;
  advantage1: string | null;
  advantage2: string | null;
  exemplary_scenario: string | null;
  detailed_exemplary_scenario: string | null;
  best_working_method: string | null;
  change_reason: string | null;
  created_by: string | null;
}

// ---------------------------------------------------------------------------
// AI Drafting
// ---------------------------------------------------------------------------

export const SECTION_TYPES = [
  "ABSTRACT",
  "BACKGROUND",
  "SUMMARY",
  "DESCRIPTION",
  "CLAIMS",
] as const;
export type SectionType = (typeof SECTION_TYPES)[number];

export const SECTION_LABELS: Record<SectionType, string> = {
  ABSTRACT: "Abstract",
  BACKGROUND: "Background",
  SUMMARY: "Summary",
  DESCRIPTION: "Detailed Description",
  CLAIMS: "Claims",
};

export interface AIOutputOut {
  id: string;
  patent_application_id: string;
  questionnaire_version_id: string;
  section_type: string;
  version_number: number;
  ai_provider: string | null;
  ai_model: string | null;
  ai_response: string | null;
  processing_status: "Processing" | "Completed" | "Failed" | null;
  input_tokens: number | null;
  output_tokens: number | null;
  created_at: string;
}

export interface DraftSectionSlot {
  section_type: string;
  latest: AIOutputOut | null;
}

// ---------------------------------------------------------------------------
// Document generation
// ---------------------------------------------------------------------------

export interface DocumentOut {
  id: string;
  patent_application_id: string;
  template_id: string | null;
  document_type: string | null;
  output_format: string;
  watermark_status: string | null;
  generated_by: string | null;
  generated_at: string | null;
}

export interface DocumentVersionOut {
  id: string;
  document_id: string;
  version_number: number;
  change_summary: string | null;
  generated_by: string | null;
  generated_at: string | null;
}

export type DocumentGenerationJobStatus = "Queued" | "Processing" | "Completed" | "Failed";

export interface DocumentGenerationJobOut {
  id: string;
  patent_application_id: string;
  status: DocumentGenerationJobStatus;
  output_format: string | null;
  triggered_by: string;
  retried_from_job_id: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

/** Badge color per lifecycle status — grouped loosely by stage. */
export const STATUS_COLOR: Record<string, string> = {
  Draft: "bg-slate-100 text-slate-600",
  Submitted: "bg-blue-100 text-blue-700",
  "Awaiting Patent Agent Acceptance": "bg-amber-100 text-amber-700",
  "Under Review": "bg-indigo-100 text-indigo-700",
  "Changes Requested": "bg-orange-100 text-orange-700",
  "Ready for Draft Generation": "bg-indigo-100 text-indigo-700",
  "Draft Generated": "bg-indigo-100 text-indigo-700",
  "Ready for Filing": "bg-teal-100 text-teal-700",
  Filed: "bg-teal-100 text-teal-700",
  "Examination Requested": "bg-teal-100 text-teal-700",
  "FER Received": "bg-orange-100 text-orange-700",
  "FER Response Submitted": "bg-teal-100 text-teal-700",
  "Hearing Scheduled": "bg-teal-100 text-teal-700",
  Granted: "bg-emerald-100 text-emerald-700",
  Rejected: "bg-red-100 text-red-700",
  Withdrawn: "bg-slate-100 text-slate-500",
  Abandoned: "bg-slate-100 text-slate-500",
};

// ---------------------------------------------------------------------------
// Collaboration: Comments, Files, Notifications, Calendar
// ---------------------------------------------------------------------------

export interface CommentOut {
  id: string;
  patent_application_id: string;
  user_id: string;
  user_full_name: string | null;
  comment_text: string;
  created_at: string;
}

export interface FileOut {
  id: string;
  patent_application_id: string;
  uploaded_by: string | null;
  uploaded_by_name: string | null;
  original_file_name: string | null;
  /** Set when a PDF was converted to Word on upload. */
  source_file_name: string | null;
  converted_from_pdf: boolean;
  mime_type: string | null;
  file_size_bytes: number | null;
  /** Best-effort text/figure extraction, run once after the upload is stored.
   * `not_analyzed` marks a file uploaded before extraction existed. */
  extraction_status:
    | "not_analyzed"
    | "pending"
    | "ready"
    | "failed"
    | "unsupported"
    | "unavailable";
  extraction_figure_count: number;
  extraction_page_count: number;
  extraction_text_available: boolean;
  extraction_error: string | null;
  created_at: string;
}

export type NotificationType =
  | "Submitted"
  | "Assigned"
  | "Accepted"
  | "Rejected"
  | "Reassigned"
  | "ChangeRequested"
  | "DraftGenerated"
  | "FilingRecorded"
  | "Granted"
  | "CommentAdded"
  | "FileUploaded"
  | string;

export interface NotificationOut {
  id: string;
  patent_application_id: string | null;
  invention_title: string | null;
  notification_type: NotificationType | null;
  is_read: boolean;
  created_at: string;
}

/** Fixed per-type template — notifications carry no free-text body, only
 * a type + the patent's title (joined in by the API). */
export const NOTIFICATION_TEXT: Record<string, (title: string) => string> = {
  Submitted: (t) => `"${t}" was submitted for review.`,
  Assigned: (t) => `You were assigned to "${t}".`,
  Accepted: (t) => `Your Patent Agent accepted "${t}".`,
  Rejected: (t) => `Your Patent Agent declined "${t}".`,
  Reassigned: (t) => `You were reassigned off "${t}" by an admin.`,
  ChangeRequested: (t) => `Changes were requested on "${t}".`,
  DraftGenerated: (t) => `A new draft was generated for "${t}".`,
  FilingRecorded: (t) => `A filing was recorded for "${t}".`,
  Granted: (t) => `"${t}" was granted.`,
  CommentAdded: (t) => `A new comment was posted on "${t}".`,
  FileUploaded: (t) => `A new file was uploaded to "${t}".`,
};

export const CALENDAR_EVENT_TYPES = ["Filing Deadline", "Examination", "Hearing", "Reminder"] as const;
export type CalendarEventType = (typeof CALENDAR_EVENT_TYPES)[number];

export interface CalendarEventOut {
  id: string;
  patent_application_id: string;
  invention_title: string | null;
  event_type: string | null;
  event_date: string | null;
  created_by: string | null;
}

export interface CalendarEventCreate {
  event_type: CalendarEventType;
  event_date: string; // ISO datetime
}

// ---------------------------------------------------------------------------
// Templates
// ---------------------------------------------------------------------------

export interface TemplateOut {
  id: string;
  document_type: string;
  version_number: number;
  file_path: string | null;
  original_file_name: string | null;
  is_active: boolean;
  edited_by: string | null;
  edited_by_name: string | null;
  // Only populated on the upload response itself — null on every other read
  // (list, activate).
  unknown_placeholders: string[] | null;
  unused_known_placeholders: string[] | null;
  template_parse_error: string | null;
}

// ---------------------------------------------------------------------------
// Reports & Dashboards
// ---------------------------------------------------------------------------

export interface StatusCount {
  status: string;
  count: number;
}

export interface RecentActivityItem {
  id: string;
  user_id: string | null;
  event_type: string | null;
  entity_type: string | null;
  entity_id: string | null;
  created_at: string;
}

export interface DashboardSummary {
  total_visible_patents: number;
  status_counts: StatusCount[];
  action_required_count: number;
  action_required_label: string;
  unread_notifications: number;
  upcoming_events_count: number;
  // Admin/Super Admin only — null for every other role.
  recent_activity: RecentActivityItem[] | null;
}

export interface ReportTypeOut {
  report_type: string;
  label: string;
  description: string;
  can_download: boolean;
}

export interface ReportOut {
  report_type: string;
  label: string;
  generated_at: string;
  row_count: number;
  rows: Record<string, string | number | null>[];
}

export interface ReportPermissionGrant {
  /** Catalog constant — numeric by design. */
  role_id: number;
  report_type: string;
}

export interface ReportTypeCatalogOut {
  report_type: string;
  label: string;
  description: string;
}

export interface ReportPermissionMatrixResponse {
  roles: RoleOut[];
  report_types: ReportTypeCatalogOut[];
  grants: ReportPermissionGrant[];
}

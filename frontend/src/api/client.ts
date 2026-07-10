export type DocType = "passport" | "g28";

export interface DocumentSummary {
  id: string;
  doc_type: DocType;
  status: string;
  file_count: number;
  case_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentFile {
  id: string;
  original_filename: string;
  content_type: string;
  file_size: number;
  page_order: number;
  created_at: string;
}

export interface Extraction {
  data: Record<string, unknown>;
  raw_text: string | null;
  error: string | null;
  created_at: string;
}

export interface Document {
  id: string;
  application_id: string | null;
  doc_type: DocType;
  status: string;
  created_at: string;
  updated_at: string;
  files: DocumentFile[];
  extraction: Extraction | null;
}

export interface ApplicationSummary {
  id: string;
  case_id: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface FormFillField {
  selector: string;
  label: string;
  input_type: string;
  options: string[] | null;
}

export interface FormFillRunSummary {
  id: string;
  case_id: string | null;
  form_url: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface FormFillRun extends FormFillRunSummary {
  fields: FormFillField[];
  mapping: Record<string, string>;
  error: string | null;
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  return handle(await fetch("/api/documents"));
}

export async function getDocument(id: string): Promise<Document> {
  return handle(await fetch(`/api/documents/${id}`));
}

export async function uploadDocument(
  docType: DocType,
  files: FileList | File[],
  caseId: string,
): Promise<Document> {
  const form = new FormData();
  form.append("doc_type", docType);
  for (const file of Array.from(files)) form.append("files", file);
  form.append("case_id", caseId.trim());
  return handle(
    await fetch("/api/documents", { method: "POST", body: form }),
  );
}

export async function listApplications(): Promise<ApplicationSummary[]> {
  return handle(await fetch("/api/applications"));
}

export async function createFormFillRun(
  caseId: string,
  formUrl: string,
): Promise<FormFillRun> {
  return handle(
    await fetch("/api/form-fill-runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ case_id: caseId, form_url: formUrl }),
    }),
  );
}

export async function listFormFillRuns(): Promise<FormFillRunSummary[]> {
  return handle(await fetch("/api/form-fill-runs"));
}

export async function getFormFillRun(id: string): Promise<FormFillRun> {
  return handle(await fetch(`/api/form-fill-runs/${id}`));
}

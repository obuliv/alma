export type DocType = "passport" | "g28";

export interface DocumentSummary {
  id: string;
  doc_type: DocType;
  status: string;
  file_count: number;
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
): Promise<Document> {
  const form = new FormData();
  form.append("doc_type", docType);
  for (const file of Array.from(files)) form.append("files", file);
  return handle(
    await fetch("/api/documents", { method: "POST", body: form }),
  );
}

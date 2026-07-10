import { useRef, useState } from "react";
import { DocType, uploadDocument } from "../api/client";

interface Props {
  onUploaded: () => void;
}

export default function UploadForm({ onUploaded }: Props) {
  const [docType, setDocType] = useState<DocType>("passport");
  const [caseId, setCaseId] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (files.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      await uploadDocument(docType, files, caseId);
      setFiles([]);
      if (inputRef.current) inputRef.current.value = "";
      onUploaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={handleSubmit}>
      {error && <div className="error">{error}</div>}

      <label htmlFor="case-id">Case ID (optional — groups passport + G-28)</label>
      <input
        id="case-id"
        type="text"
        placeholder="e.g. CASE-1024"
        value={caseId}
        onChange={(e) => setCaseId(e.target.value)}
      />

      <label htmlFor="doc-type">Document type</label>
      <select
        id="doc-type"
        value={docType}
        onChange={(e) => setDocType(e.target.value as DocType)}
      >
        <option value="passport">Passport</option>
        <option value="g28">G-28</option>
      </select>

      <label htmlFor="files">
        Files (PDF, JPEG, or PNG — select multiple pages if needed)
      </label>
      <input
        id="files"
        ref={inputRef}
        type="file"
        multiple
        accept="application/pdf,image/jpeg,image/png"
        onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
      />

      {files.length > 0 && (
        <ul className="file-list">
          {files.map((f, i) => (
            <li key={i}>
              {i + 1}. {f.name} ({Math.round(f.size / 1024)} KB)
            </li>
          ))}
        </ul>
      )}

      <button type="submit" disabled={busy || files.length === 0}>
        {busy ? "Uploading…" : "Upload document"}
      </button>
    </form>
  );
}

import { useRef, useState } from "react";
import { uploadDocument } from "../api/client";

interface Props {
  onUploaded: () => void;
}

function FileField({
  id,
  label,
  files,
  onChange,
  inputRef,
}: {
  id: string;
  label: string;
  files: File[];
  onChange: (files: File[]) => void;
  inputRef: React.RefObject<HTMLInputElement>;
}) {
  return (
    <>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        ref={inputRef}
        type="file"
        multiple
        accept="application/pdf,image/jpeg,image/png"
        onChange={(e) => onChange(Array.from(e.target.files ?? []))}
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
    </>
  );
}

export default function UploadForm({ onUploaded }: Props) {
  const [caseId, setCaseId] = useState("");
  const [passportFiles, setPassportFiles] = useState<File[]>([]);
  const [g28Files, setG28Files] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const passportInputRef = useRef<HTMLInputElement>(null);
  const g28InputRef = useRef<HTMLInputElement>(null);

  const canSubmit =
    caseId.trim().length > 0 && passportFiles.length > 0 && g28Files.length > 0;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      await uploadDocument("passport", passportFiles, caseId);
      await uploadDocument("g28", g28Files, caseId);
      setPassportFiles([]);
      setG28Files([]);
      if (passportInputRef.current) passportInputRef.current.value = "";
      if (g28InputRef.current) g28InputRef.current.value = "";
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

      <label htmlFor="case-id">Case ID (required — groups this passport + G-28)</label>
      <input
        id="case-id"
        type="text"
        placeholder="e.g. CASE-1024"
        value={caseId}
        onChange={(e) => setCaseId(e.target.value)}
        required
      />

      <FileField
        id="passport-files"
        label="Passport files (PDF, JPEG, or PNG — select multiple pages if needed)"
        files={passportFiles}
        onChange={setPassportFiles}
        inputRef={passportInputRef}
      />

      <FileField
        id="g28-files"
        label="G-28 files (PDF, JPEG, or PNG — select multiple pages if needed)"
        files={g28Files}
        onChange={setG28Files}
        inputRef={g28InputRef}
      />

      <button type="submit" disabled={busy || !canSubmit}>
        {busy ? "Uploading…" : "Upload passport + G-28"}
      </button>
    </form>
  );
}

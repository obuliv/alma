import { useEffect, useState } from "react";
import {
  ApplicationSummary,
  createFormFillRun,
  listApplications,
} from "../api/client";

interface Props {
  onCreated: () => void;
}

export default function FormFillForm({ onCreated }: Props) {
  const [applications, setApplications] = useState<ApplicationSummary[]>([]);
  const [caseId, setCaseId] = useState("");
  const [formUrl, setFormUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listApplications()
      .then((apps) => {
        const withCaseId = apps.filter((a) => a.case_id);
        setApplications(withCaseId);
        if (withCaseId.length > 0) setCaseId((c) => c || withCaseId[0].case_id!);
      })
      .catch(() => {
        /* leave the list empty on transient errors */
      });
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!caseId || !formUrl.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await createFormFillRun(caseId, formUrl.trim());
      setFormUrl("");
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Form-fill run failed to start");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={handleSubmit}>
      {error && <div className="error">{error}</div>}

      <label htmlFor="ff-case-id">Case ID</label>
      {applications.length > 0 ? (
        <select
          id="ff-case-id"
          value={caseId}
          onChange={(e) => setCaseId(e.target.value)}
        >
          {applications.map((a) => (
            <option key={a.id} value={a.case_id!}>
              {a.case_id}
            </option>
          ))}
        </select>
      ) : (
        <p className="muted">
          No cases yet — upload a document with a Case ID first.
        </p>
      )}

      <label htmlFor="ff-form-url">Form URL</label>
      <input
        id="ff-form-url"
        type="text"
        placeholder="https://example.com/form"
        value={formUrl}
        onChange={(e) => setFormUrl(e.target.value)}
      />

      <button type="submit" disabled={busy || !caseId || !formUrl.trim()}>
        {busy ? "Starting…" : "Fill form"}
      </button>
    </form>
  );
}

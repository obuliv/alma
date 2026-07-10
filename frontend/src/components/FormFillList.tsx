import { useEffect, useState } from "react";
import {
  FormFillRun,
  FormFillRunSummary,
  getFormFillRun,
  listFormFillRuns,
} from "../api/client";

interface Props {
  refreshKey: number;
}

const POLL_MS = 2500;

export default function FormFillList({ refreshKey }: Props) {
  const [runs, setRuns] = useState<FormFillRunSummary[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [detail, setDetail] = useState<FormFillRun | null>(null);

  async function refresh() {
    try {
      setRuns(await listFormFillRuns());
    } catch {
      /* keep last known list on transient errors */
    }
  }

  // Poll so status transitions (filling → filled) show without a reload.
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refreshKey]);

  async function toggle(id: string) {
    if (expanded === id) {
      setExpanded(null);
      setDetail(null);
      return;
    }
    setExpanded(id);
    setDetail(await getFormFillRun(id));
  }

  if (runs.length === 0) {
    return <p className="muted">No form-fill runs yet.</p>;
  }

  return (
    <div className="card">
      {runs.map((run) => (
        <div key={run.id}>
          <div
            className="doc-row"
            onClick={() => toggle(run.id)}
            style={{ cursor: "pointer" }}
          >
            <div>
              <strong>{run.case_id ?? "(no case)"}</strong>{" "}
              <span className="muted">· {run.form_url}</span>
            </div>
            <span className={`badge ${run.status}`}>{run.status}</span>
          </div>
          {expanded === run.id && (
            <div className="muted" style={{ paddingBottom: "0.75rem" }}>
              {!detail && "Loading…"}
              {detail?.status === "filling" && (
                <p>Figuring out the mapping and opening the browser…</p>
              )}
              {detail?.status === "filled" && (
                <>
                  <p>
                    Filled. Review, correct, and submit in the Chromium window
                    on your machine.
                  </p>
                  <pre style={{ whiteSpace: "pre-wrap" }}>
                    {JSON.stringify(detail.mapping, null, 2)}
                  </pre>
                </>
              )}
              {detail?.status === "failed" && (
                <div className="error">{detail.error}</div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

import { useEffect, useState } from "react";
import { DocumentSummary, getDocument, listDocuments } from "../api/client";

interface Props {
  refreshKey: number;
}

const POLL_MS = 2500;

export default function DocumentList({ refreshKey }: Props) {
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);

  async function refresh() {
    try {
      setDocs(await listDocuments());
    } catch {
      /* keep last known list on transient errors */
    }
  }

  // Poll so status transitions (uploaded → extracted) show without a reload.
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
    const doc = await getDocument(id);
    setDetail(doc.extraction?.data ?? null);
  }

  if (docs.length === 0) {
    return <p className="muted">No documents uploaded yet.</p>;
  }

  return (
    <div className="card">
      {docs.map((doc) => (
        <div key={doc.id}>
          <div className="doc-row" onClick={() => toggle(doc.id)} style={{ cursor: "pointer" }}>
            <div>
              <strong>{doc.doc_type === "g28" ? "G-28" : "Passport"}</strong>{" "}
              <span className="muted">
                · {doc.file_count} file{doc.file_count === 1 ? "" : "s"}
              </span>
            </div>
            <span className={`badge ${doc.status}`}>{doc.status}</span>
          </div>
          {expanded === doc.id && (
            <pre className="muted" style={{ whiteSpace: "pre-wrap" }}>
              {detail
                ? JSON.stringify(detail, null, 2)
                : "No extraction data yet."}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}

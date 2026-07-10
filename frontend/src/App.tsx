import { useState } from "react";
import UploadForm from "./components/UploadForm";
import DocumentList from "./components/DocumentList";
import FormFillForm from "./components/FormFillForm";
import FormFillList from "./components/FormFillList";

type Tab = "documents" | "formfill";

export default function App() {
  const [tab, setTab] = useState<Tab>("documents");
  const [refreshKey, setRefreshKey] = useState(0);
  const [runRefreshKey, setRunRefreshKey] = useState(0);

  return (
    <div className="container">
      <h1>Alma — Document Upload</h1>
      <p className="subtitle">
        Upload a case's passport and G-28 together (PDF, JPEG, or PNG), grouped
        by Case ID, then fill a target form from the extracted data.
      </p>

      <div className="tabs">
        <button
          className={tab === "documents" ? "tab active" : "tab"}
          onClick={() => setTab("documents")}
        >
          Documents
        </button>
        <button
          className={tab === "formfill" ? "tab active" : "tab"}
          onClick={() => setTab("formfill")}
        >
          Form Fill
        </button>
      </div>

      {tab === "documents" && (
        <>
          <UploadForm onUploaded={() => setRefreshKey((k) => k + 1)} />
          <h2 style={{ fontSize: "1.1rem" }}>Documents</h2>
          <DocumentList refreshKey={refreshKey} />
        </>
      )}

      {tab === "formfill" && (
        <>
          <FormFillForm onCreated={() => setRunRefreshKey((k) => k + 1)} />
          <h2 style={{ fontSize: "1.1rem" }}>Form Fill Runs</h2>
          <FormFillList refreshKey={runRefreshKey} />
        </>
      )}
    </div>
  );
}

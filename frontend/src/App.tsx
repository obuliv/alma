import { useState } from "react";
import UploadForm from "./components/UploadForm";
import DocumentList from "./components/DocumentList";

export default function App() {
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <div className="container">
      <h1>Alma — Document Upload</h1>
      <p className="subtitle">
        Upload a case's passport and G-28 together (PDF, JPEG, or PNG), grouped
        by Case ID.
      </p>

      <UploadForm onUploaded={() => setRefreshKey((k) => k + 1)} />

      <h2 style={{ fontSize: "1.1rem" }}>Documents</h2>
      <DocumentList refreshKey={refreshKey} />
    </div>
  );
}

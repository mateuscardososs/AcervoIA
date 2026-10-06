import type { AskSource } from "../api/client";

export function SourceCard({ source }: { source: AskSource }) {
  return (
    <article className="source-card" aria-label={`Fonte ${source.source_id}`}>
      <div className="source-card-heading">
        <span className="source-marker">[{source.source_id}]</span>
        <span className="source-document">{source.document_name}</span>
        {source.page_number !== null && (
          <span className="source-page">Página {source.page_number}</span>
        )}
      </div>
      <p className="source-snippet">{source.snippet}</p>
    </article>
  );
}

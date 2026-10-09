import type { AskSource } from "../api/client";

type SourceCardProps = {
  source: AskSource;
  onOpenDocument: (source: AskSource) => void;
  opening: boolean;
};

export function SourceCard({ source, onOpenDocument, opening }: SourceCardProps) {
  const isPdf = source.document_name.toLowerCase().endsWith(".pdf");
  const actionLabel = isPdf
    ? source.page_number === null
      ? "Abrir PDF"
      : `Abrir PDF na página ${source.page_number}`
    : "Baixar arquivo original";

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
      <div className="source-card-actions">
        <button
          className="button button-secondary source-open-button"
          disabled={opening}
          onClick={() => onOpenDocument(source)}
          type="button"
        >
          {opening ? "Abrindo…" : actionLabel}
        </button>
      </div>
    </article>
  );
}

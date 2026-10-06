import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  api,
  ApiError,
  type Collection,
  type DocumentRecord,
} from "../api/client";
import { LoadingState } from "../components/LoadingState";

function documentStatus(status: DocumentRecord["processing_status"]): string {
  return {
    pending: "Aguardando processamento",
    processing: "Processando",
    completed: "Processado",
    failed: "Falha no processamento",
  }[status];
}

export function DocumentDetailPage() {
  const { collectionId = "", documentId = "" } = useParams();
  const [collection, setCollection] = useState<Collection | null>(null);
  const [document, setDocument] = useState<DocumentRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [active, setActive] = useState(false);
  const [step, setStep] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function refresh() {
    try {
      const [collectionData, documentList] = await Promise.all([
        api.collection(collectionId),
        api.documents(collectionId),
      ]);
      setCollection(collectionData);
      setDocument(documentList.find((item) => item.id === documentId) ?? null);
    } catch {
      setError("Não foi possível abrir este documento. Ele pode não pertencer a esta coleção.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let current = true;
    setLoading(true);
    setCollection(null);
    setDocument(null);
    setError(null);
    Promise.all([api.collection(collectionId), api.documents(collectionId)])
      .then(([collectionData, documentList]) => {
        if (!current) return;
        setCollection(collectionData);
        setDocument(documentList.find((item) => item.id === documentId) ?? null);
      })
      .catch(() => {
        if (current) setError("Não foi possível abrir este documento. Ele pode não pertencer a esta coleção.");
      })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [collectionId, documentId]);

  async function process() {
    if (!document) return;
    setActive(true);
    setError(null);
    setNotice(null);
    setStep("Extraindo texto…");
    setDocument({ ...document, processing_status: "processing", processing_error: null });
    try {
      const processed = await api.processDocument(collectionId, document.id);
      setDocument((current) => current ? {
        ...current,
        processing_status: processed.processing_status as DocumentRecord["processing_status"],
        processing_error: null,
      } : current);
      setStep("Preparando busca vetorial…");
      const result = await api.embedDocument(collectionId, document.id);
      setStep(null);
      setNotice(`${result.chunk_count} trechos extraídos e preparados para consulta.`);
    } catch (cause) {
      setStep(null);
      if (cause instanceof ApiError && cause.status === 503) {
        setError("Ollama indisponível. Inicie o serviço local e confira se o modelo de embeddings está instalado.");
        setNotice("O texto foi processado; os vetores podem ser gerados novamente depois.");
      } else if (cause instanceof ApiError && cause.status === 422) {
        setError("Não foi possível extrair texto deste arquivo. O documento foi mantido para uma nova tentativa.");
        await refresh();
      } else {
        setError("Não foi possível processar o documento. Verifique o estado e tente novamente.");
        await refresh();
      }
    } finally {
      setActive(false);
    }
  }

  if (loading) return <div className="page-content"><LoadingState label="Carregando documento…" /></div>;
  if (!collection || !document) {
    return (
      <div className="page-content">
        <p className="notice notice-error" role="alert">{error || "Documento não encontrado nesta coleção."}</p>
        <Link to={`/collections/${collectionId}`}>Voltar à coleção</Link>
      </div>
    );
  }

  const extension = document.original_filename.split(".").pop()?.toUpperCase() ?? "ARQUIVO";
  return (
    <div className="page-content">
      <nav aria-label="Trilha de navegação" className="breadcrumbs">
        <Link to="/library">Meu acervo</Link><span aria-hidden="true">/</span>
        <Link to={`/collections/${collection.id}`}>{collection.name}</Link><span aria-hidden="true">/</span>
        <span>{document.original_filename}</span>
      </nav>
      <header className="page-header document-detail-header">
        <div>
          <p className="eyebrow">DETALHES DO DOCUMENTO · {extension}</p>
          <h1>{document.original_filename}</h1>
          <p className="page-subtitle">Parte da coleção <Link to={`/collections/${collection.id}`}>{collection.name}</Link></p>
        </div>
        <Link className="button button-primary" to={`/collections/${collection.id}/ask`}>
          Perguntar à coleção <span aria-hidden="true">→</span>
        </Link>
      </header>

      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {notice && <p className="notice notice-success" role="status">{notice}</p>}

      <section className="document-detail-panel" aria-labelledby="document-status-heading">
        <div className="document-detail-state">
          <div className={`detail-file-mark detail-${document.processing_status}`} aria-hidden="true">{extension.slice(0, 3)}</div>
          <div>
            <p className="eyebrow">ESTADO ATUAL</p>
            <h2 id="document-status-heading">{documentStatus(document.processing_status)}</h2>
            <p>{document.processing_error || "Extraia o texto e prepare os trechos para pesquisar este documento."}</p>
          </div>
          <span className={`status-pill status-${document.processing_status}`}><span className="status-dot" />{documentStatus(document.processing_status)}</span>
        </div>

        {step && <LoadingState label={step} />}
        <div className="document-detail-actions">
          <button className="button button-primary" disabled={active} onClick={() => void process()} type="button">
            {active ? "Processando…" : document.processing_status === "completed" ? "Reprocessar e atualizar busca" : "Processar documento"}
          </button>
          <Link className="button button-secondary" to={`/collections/${collection.id}`}>Voltar à coleção</Link>
        </div>
      </section>

      <section className="metadata-section" aria-labelledby="metadata-heading">
        <div className="section-heading">
          <div><p className="eyebrow">REGISTRO</p><h2 id="metadata-heading">Metadados</h2></div>
        </div>
        <dl className="metadata-grid">
          <div><dt>Nome do arquivo</dt><dd>{document.original_filename}</dd></div>
          <div><dt>Formato</dt><dd>{document.content_type}</dd></div>
          <div><dt>Tamanho</dt><dd>{(document.size_bytes / (1024 * 1024)).toFixed(2)} MiB</dd></div>
          <div><dt>Enviado em</dt><dd>{new Date(document.created_at).toLocaleString("pt-BR")}</dd></div>
        </dl>
      </section>
    </div>
  );
}

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import {
  api,
  ApiError,
  type Collection,
  type DocumentRecord,
} from "../api/client";
import { LoadingState } from "../components/LoadingState";

const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".txt"];
const MAX_FILE_BYTES = 20 * 1024 * 1024;

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function processingLabel(status: DocumentRecord["processing_status"]): string {
  switch (status) {
    case "pending": return "Aguardando processamento";
    case "processing": return "Processando";
    case "completed": return "Processado";
    case "failed": return "Falha no processamento";
  }
}

export function CollectionPage() {
  const { collectionId = "" } = useParams();
  const [collection, setCollection] = useState<Collection | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const loadSequence = useRef(0);

  async function refresh() {
    const sequence = ++loadSequence.current;
    setError(null);
    try {
      const [collectionData, documentData] = await Promise.all([
        api.collection(collectionId),
        api.documents(collectionId),
      ]);
      if (sequence === loadSequence.current) {
        setCollection(collectionData);
        setDocuments(documentData);
      }
    } catch {
      if (sequence === loadSequence.current) {
        setError("Não foi possível carregar esta coleção. Ela pode não existir ou não pertencer à sua conta.");
      }
    } finally {
      if (sequence === loadSequence.current) setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    setCollection(null);
    setDocuments([]);
    void refresh();
    return () => { loadSequence.current += 1; };
  }, [collectionId]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!selectedFile) {
      setError("Escolha um arquivo antes de enviar.");
      return;
    }
    const extension = selectedFile.name.slice(selectedFile.name.lastIndexOf(".")).toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(extension)) {
      setError("Envie um arquivo PDF, DOCX ou TXT.");
      return;
    }
    if (selectedFile.size > MAX_FILE_BYTES) {
      setError("O arquivo excede o limite de 20 MiB.");
      return;
    }

    setUploading(true);
    setError(null);
    setNotice(null);
    try {
      const created = await api.uploadDocument(collectionId, selectedFile);
      setDocuments((items) => [...items, created]);
      setSelectedFile(null);
      form.reset();
      setNotice("Arquivo enviado. Processe-o para extrair os trechos.");
    } catch (cause) {
      setError(cause instanceof ApiError && cause.status === 413
        ? "O arquivo excede o limite de 20 MiB."
        : cause instanceof ApiError && cause.status === 400
          ? "O arquivo não é válido ou não é aceito."
          : "Não foi possível enviar o arquivo. Tente novamente.");
    } finally {
      setUploading(false);
    }
  }

  async function remove(document: DocumentRecord) {
    setError(null);
    try {
      await api.deleteDocument(collectionId, document.id);
      setDocuments((items) => items.filter((item) => item.id !== document.id));
    } catch {
      setError("Não foi possível remover o documento. Atualize a página e tente novamente.");
    }
  }

  if (loading) return <div className="page-content"><LoadingState label="Abrindo coleção…" /></div>;
  if (error && !collection) return <div className="page-content"><p className="notice notice-error" role="alert">{error}</p><Link to="/library">Voltar ao acervo</Link></div>;
  if (!collection) return null;

  return (
    <div className="page-content">
      <nav aria-label="Trilha de navegação" className="breadcrumbs">
        <Link to="/library">Meu acervo</Link><span aria-hidden="true">/</span><span>{collection.name}</span>
      </nav>
      <header className="page-header collection-page-header">
        <div>
          <p className="eyebrow">COLEÇÃO · {documents.length} {documents.length === 1 ? "DOCUMENTO" : "DOCUMENTOS"}</p>
          <h1>{collection.name}</h1>
          <p className="page-subtitle">{collection.description || "Documentos e trechos desta coleção."}</p>
        </div>
        <Link className="button button-primary" to={`/collections/${collection.id}/ask`}>
          Consultar coleção <span aria-hidden="true">→</span>
        </Link>
      </header>

      <section className="upload-panel" aria-labelledby="upload-title">
        <div className="upload-intro">
          <span className="upload-symbol" aria-hidden="true">↑</span>
          <div>
            <p className="eyebrow">ADICIONAR À COLEÇÃO</p>
            <h2 id="upload-title">Enviar um documento</h2>
            <p>PDF, DOCX ou TXT · até 20 MiB por arquivo</p>
          </div>
        </div>
        <form className="upload-form" onSubmit={(event) => void upload(event)}>
          <label className="file-picker" htmlFor="document-file">
            <span>{selectedFile?.name ?? "Escolher arquivo…"}</span>
            <input
              accept=".pdf,.docx,.txt"
              aria-label="Enviar documento"
              id="document-file"
              onChange={(event) => setSelectedFile(event.currentTarget.files?.[0] ?? null)}
              type="file"
            />
          </label>
          <button className="button button-primary" disabled={uploading || !selectedFile} type="submit">
            {uploading ? "Enviando…" : "Enviar arquivo"}
          </button>
        </form>
      </section>

      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {notice && <p className="notice notice-success" role="status">{notice}</p>}

      <section className="document-section" aria-labelledby="documents-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">ARQUIVOS DA COLEÇÃO</p>
            <h2 id="documents-title">Documentos</h2>
          </div>
          <span className="mono-label">{documents.length.toString().padStart(2, "0")} ITENS</span>
        </div>
        {documents.length === 0 ? (
          <div className="empty-inline">
            <p>Ainda não há documentos nesta coleção.</p>
            <p>Envie um manual acima para começar.</p>
          </div>
        ) : (
          <div className="document-list">
            {documents.map((document) => (
              <article className="document-row" key={document.id}>
                <span className="file-type" aria-hidden="true">{document.original_filename.split(".").pop()?.toUpperCase()}</span>
                <div className="document-meta">
                  <h3>
                    <Link
                      aria-label={`Detalhes de ${document.original_filename}`}
                      className="document-title-link"
                      to={`/collections/${collectionId}/documents/${document.id}`}
                    >
                      {document.original_filename}
                    </Link>
                  </h3>
                  <p>{formatSize(document.size_bytes)} <span aria-hidden="true">·</span> {new Date(document.created_at).toLocaleDateString("pt-BR")}</p>
                  {document.processing_error && <p className="document-error">{document.processing_error}</p>}
                </div>
                <span className={`status-pill status-${document.processing_status}`}>
                  <span className="status-dot" />{processingLabel(document.processing_status)}
                </span>
                <div className="document-actions">
                  <Link
                    className="button button-secondary button-small"
                    to={`/collections/${collectionId}/documents/${document.id}`}
                  >Detalhes</Link>
                  <button
                    aria-label={`Excluir ${document.original_filename}`}
                    className="icon-button icon-button-danger"
                    onClick={() => void remove(document)}
                    type="button"
                  >×</button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

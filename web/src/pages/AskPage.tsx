import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import {
  api,
  ApiError,
  type AskHistoryItem,
  type AskResponse,
  type Collection,
  type SearchStrategy,
} from "../api/client";
import { LoadingState } from "../components/LoadingState";
import { SourceCard } from "../components/SourceCard";

const STRATEGIES: { id: SearchStrategy; label: string }[] = [
  { id: "vector", label: "Vetorial" },
  { id: "text", label: "Textual" },
  { id: "hybrid", label: "Híbrida" },
];
const HISTORY_PAGE_SIZE = 20;

export function AskPage() {
  const { collectionId = "" } = useParams();
  const [collection, setCollection] = useState<Collection | null>(null);
  const [loading, setLoading] = useState(true);
  const [question, setQuestion] = useState("");
  const [strategy, setStrategy] = useState<SearchStrategy>("vector");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<AskHistoryItem[]>([]);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [historyHasMore, setHistoryHasMore] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [openingDocumentId, setOpeningDocumentId] = useState<string | null>(null);
  const [sourceFileError, setSourceFileError] = useState<string | null>(null);

  async function loadHistoryPage(offset = 0, append = false) {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const page = await api.questionHistory(collectionId, HISTORY_PAGE_SIZE, offset);
      setHistory((current) => append ? [...current, ...page.items] : page.items);
      setHistoryOffset(offset + page.items.length);
      setHistoryHasMore(page.has_more);
    } catch {
      setHistoryError("Não foi possível carregar o histórico desta coleção.");
    } finally {
      setHistoryLoading(false);
    }
  }

  useEffect(() => {
    let current = true;
    api.collection(collectionId)
      .then((data) => {
        if (!current) return;
        setCollection(data);
        void loadHistoryPage();
      })
      .catch(() => { if (current) setError("Não foi possível abrir esta coleção."); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [collectionId]);

  async function askQuestion(questionText: string, selectedStrategy: SearchStrategy) {
    setAsking(true);
    setAnswer(null);
    setError(null);
    try {
      setAnswer(await api.ask(collectionId, questionText, selectedStrategy));
      await loadHistoryPage();
    } catch (cause) {
      setError(cause instanceof ApiError && cause.status === 503
        ? "O serviço local de IA (Ollama) está indisponível. Confira se está em execução e se os modelos configurados de embeddings e chat foram instalados."
        : cause instanceof ApiError && cause.status === 502
          ? "A resposta do modelo não pôde ser validada. Nenhuma fonte foi exibida; tente novamente ou reformule a pergunta."
          : cause instanceof ApiError && cause.status === 401
            ? "Sua sessão expirou. Entre novamente para continuar."
            : "Não foi possível consultar os documentos desta coleção. Tente novamente.");
    } finally {
      setAsking(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await askQuestion(question.trim(), strategy);
  }

  async function askAgain(item: AskHistoryItem) {
    setQuestion(item.question);
    setStrategy(item.strategy);
    await askQuestion(item.question, item.strategy);
  }

  async function openSourceDocument(source: AskResponse["sources"][number]) {
    const isPdf = source.document_name.toLowerCase().endsWith(".pdf");
    const pdfWindow = isPdf ? window.open("about:blank", "_blank") : null;
    if (isPdf && !pdfWindow) {
      setSourceFileError("O navegador bloqueou a abertura do PDF. Permita pop-ups e tente novamente.");
      return;
    }

    setOpeningDocumentId(source.document_id);
    setSourceFileError(null);
    try {
      const file = await api.documentFile(collectionId, source.document_id);
      const objectUrl = URL.createObjectURL(file);
      if (isPdf && pdfWindow) {
        pdfWindow.opener = null;
        pdfWindow.location.href = `${objectUrl}#page=${source.page_number ?? 1}`;
      } else {
        const link = document.createElement("a");
        const filename = source.document_name.replaceAll("\\", "/").split("/").pop();
        link.href = objectUrl;
        link.download = filename || "documento";
        link.style.display = "none";
        document.body.append(link);
        link.click();
        link.remove();
      }
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30_000);
    } catch (cause) {
      pdfWindow?.close();
      setSourceFileError(cause instanceof ApiError && cause.status === 404
        ? "O arquivo original não está mais disponível nesta coleção."
        : cause instanceof ApiError && cause.status === 401
          ? "Sua sessão expirou. Entre novamente para abrir este documento."
          : "Não foi possível abrir o arquivo original. Tente novamente.");
    } finally {
      setOpeningDocumentId(null);
    }
  }

  if (loading) return <div className="page-content"><LoadingState label="Preparando consulta…" /></div>;
  if (!collection) return <div className="page-content"><p className="notice notice-error" role="alert">{error || "Coleção não encontrada."}</p><Link to="/library">Voltar ao acervo</Link></div>;

  return (
    <div className="page-content ask-page">
      <nav aria-label="Trilha de navegação" className="breadcrumbs">
        <Link to="/library">Meu acervo</Link><span aria-hidden="true">/</span>
        <Link to={`/collections/${collection.id}`}>{collection.name}</Link><span aria-hidden="true">/</span><span>Consulta</span>
      </nav>
      <header className="page-header ask-page-header">
        <div>
          <p className="eyebrow">CONSULTA COM FONTES</p>
          <h1>Pergunte aos documentos</h1>
          <p className="page-subtitle">{collection.name} <span className="collection-context-dot">·</span> respostas apoiadas apenas no conteúdo da coleção.</p>
        </div>
      </header>

      <form className="question-panel" onSubmit={(event) => void submit(event)}>
        <label htmlFor="question-text">Sua pergunta</label>
        <textarea
          autoFocus
          id="question-text"
          maxLength={4_000}
          onChange={(event) => setQuestion(event.currentTarget.value)}
          placeholder="Ex.: O que significa o código E-17 neste modelo?"
          required
          rows={4}
          value={question}
        />
        <div className="question-controls">
          <div className="strategy-control">
            <label htmlFor="search-strategy">Modo de busca</label>
            <select
              id="search-strategy"
              onChange={(event) => setStrategy(event.currentTarget.value as SearchStrategy)}
              value={strategy}
            >
              {STRATEGIES.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
            </select>
          </div>
          <button className="button button-primary ask-button" disabled={asking || !question.trim()} type="submit">
            {asking ? "Consultando…" : "Perguntar"}<span aria-hidden="true">→</span>
          </button>
        </div>
        <p className="query-note">A resposta usa somente os documentos desta coleção e mostra os trechos recuperados.</p>
      </form>

      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {sourceFileError && <p className="notice notice-error" role="alert">{sourceFileError}</p>}
      {asking && <LoadingState label="Buscando trechos e preparando uma resposta…" />}

      {answer && (
        <section aria-labelledby="answer-heading" className="answer-region">
          <div className="answer-heading-row">
            <div>
              <p className="eyebrow">RESPOSTA · {strategy.toUpperCase()}</p>
              <h2 id="answer-heading">Resultado da consulta</h2>
            </div>
            <span className="evidence-status"><span className="live-dot" />{answer.sources.length ? `${answer.sources.length} ${answer.sources.length === 1 ? "fonte" : "fontes"}` : "Sem fontes encontradas"}</span>
          </div>
          <div className="answer-copy"><p>{answer.answer}</p></div>
          {answer.sources.length > 0 ? (
            <div className="source-section">
              <div className="section-heading source-section-heading">
                <div><p className="eyebrow">RASTREABILIDADE</p><h3>Trechos usados</h3></div>
                <span className="mono-label">{answer.sources.length.toString().padStart(2, "0")} FONTES</span>
              </div>
              <div className="source-list">
                {answer.sources.map((source) => (
                  <SourceCard
                    key={source.source_id}
                    onOpenDocument={(citedSource) => void openSourceDocument(citedSource)}
                    opening={openingDocumentId === source.document_id}
                    source={source}
                  />
                ))}
              </div>
            </div>
          ) : (
            <p className="no-sources-note" role="status">Nenhuma fonte validada foi retornada para esta pergunta. Tente outro termo ou confira os documentos processados.</p>
          )}
        </section>
      )}

      {!answer && !asking && !error && (
        <section className="query-empty-state">
          <span className="query-glyph" aria-hidden="true">?</span>
          <div><p className="eyebrow">PRONTO PARA CONSULTAR</p><p>Faça uma pergunta específica. As fontes aparecem junto da resposta.</p></div>
        </section>
      )}

      <section aria-labelledby="history-heading" className="question-history">
        <div className="section-heading">
          <div><p className="eyebrow">CONSULTAS ANTERIORES</p><h2 id="history-heading">Histórico da coleção</h2></div>
          <span className="mono-label">{history.length.toString().padStart(2, "0")} REGISTROS</span>
        </div>
        {historyError && <p className="notice notice-error" role="status">{historyError}</p>}
        {historyLoading && history.length === 0 ? (
          <LoadingState label="Carregando histórico…" />
        ) : history.length === 0 ? (
          <p className="query-empty-state" role="status">As respostas válidas e abstenções desta coleção aparecerão aqui.</p>
        ) : (
          <div className="question-history-list">
            {history.map((item) => (
              <article className="history-card" key={item.id}>
                <div className="history-card-meta">
                  <span>{item.strategy.toUpperCase()}</span>
                  <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time>
                </div>
                <h3>{item.question}</h3>
                <p className="history-answer">{item.answer}</p>
                {item.sources.length > 0 && (
                  <div className="source-list history-source-list">
                    {item.sources.map((source) => (
                      <SourceCard
                        key={`${item.id}-${source.source_id}`}
                        onOpenDocument={(citedSource) => void openSourceDocument(citedSource)}
                        opening={openingDocumentId === source.document_id}
                        source={source}
                      />
                    ))}
                  </div>
                )}
                <button
                  className="button button-secondary history-repeat-button"
                  disabled={asking}
                  onClick={() => void askAgain(item)}
                  type="button"
                >
                  Consultar novamente
                </button>
              </article>
            ))}
          </div>
        )}
        {historyHasMore && (
          <button
            className="button button-secondary history-more-button"
            disabled={historyLoading}
            onClick={() => void loadHistoryPage(historyOffset, true)}
            type="button"
          >
            {historyLoading ? "Carregando…" : "Carregar perguntas anteriores"}
          </button>
        )}
      </section>
    </div>
  );
}

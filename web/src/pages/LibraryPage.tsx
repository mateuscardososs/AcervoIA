import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type Collection } from "../api/client";
import { LoadingState } from "../components/LoadingState";

export function LibraryPage() {
  const [collections, setCollections] = useState<Collection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Collection | null>(null);
  const [saving, setSaving] = useState(false);

  async function refresh() {
    setError(null);
    try {
      setCollections(await api.collections());
    } catch {
      setError("Não foi possível carregar suas coleções. Tente novamente.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true);
    setError(null);
    try {
      const created = await api.createCollection(
        String(form.get("name") ?? "").trim(),
        String(form.get("description") ?? "").trim(),
      );
      setCollections((items) => [...items, created]);
      setShowCreate(false);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Não foi possível criar a coleção.");
    } finally {
      setSaving(false);
    }
  }

  async function rename(event: FormEvent<HTMLFormElement>, collection: Collection) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateCollection(
        collection.id,
        String(form.get("name") ?? "").trim(),
        String(form.get("description") ?? "").trim(),
      );
      setCollections((items) => items.map((item) => item.id === updated.id ? updated : item));
      setEditing(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Não foi possível atualizar a coleção.");
    } finally {
      setSaving(false);
    }
  }

  async function removeCollection() {
    if (!deleting) return;
    setSaving(true);
    setError(null);
    try {
      await api.deleteCollection(deleting.id);
      setCollections((items) => items.filter((item) => item.id !== deleting.id));
      setDeleting(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Não foi possível excluir a coleção.");
      setDeleting(null);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page-content">
      <header className="page-header">
        <div>
          <p className="eyebrow">BIBLIOTECA · PRIVADA</p>
          <h1>Meu acervo</h1>
          <p className="page-subtitle">Manuais organizados para encontrar e conferir.</p>
        </div>
        <button className="button button-primary" onClick={() => setShowCreate(true)} type="button">
          <span aria-hidden="true">＋</span> Nova coleção
        </button>
      </header>

      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {loading ? (
        <LoadingState label="Carregando seu acervo…" />
      ) : collections.length === 0 ? (
        <section className="empty-state">
          <div className="empty-mark" aria-hidden="true">▤</div>
          <p className="eyebrow">PRIMEIRA PRATELEIRA</p>
          <h2>Seu acervo ainda está vazio</h2>
          <p>Crie uma coleção para começar a reunir seus manuais e documentos.</p>
          <button className="button button-primary" onClick={() => setShowCreate(true)} type="button">
            Criar primeira coleção
          </button>
        </section>
      ) : (
        <section aria-label="Suas coleções" className="collection-grid">
          {collections.map((collection) => (
            <article className="collection-card" key={collection.id}>
              <div className="collection-card-top">
                <span className="collection-symbol" aria-hidden="true">▤</span>
                <span className="mono-label">COLEÇÃO</span>
                <div className="collection-actions">
                  <button
                    aria-label={`Renomear ${collection.name}`}
                    className="icon-button"
                    onClick={() => setEditing(editing === collection.id ? null : collection.id)}
                    type="button"
                  >✎</button>
                  <button
                    aria-label={`Excluir ${collection.name}`}
                    className="icon-button icon-button-danger"
                    onClick={() => setDeleting(collection)}
                    type="button"
                  >×</button>
                </div>
              </div>
              {editing === collection.id ? (
                <form className="stack-form collection-edit-form" onSubmit={(event) => void rename(event, collection)}>
                  <label htmlFor={`edit-name-${collection.id}`}>Nome da coleção</label>
                  <input id={`edit-name-${collection.id}`} name="name" defaultValue={collection.name} maxLength={120} required />
                  <label htmlFor={`edit-description-${collection.id}`}>Descrição</label>
                  <input id={`edit-description-${collection.id}`} name="description" defaultValue={collection.description ?? ""} />
                  <div className="form-actions">
                    <button className="button button-secondary" onClick={() => setEditing(null)} type="button">Cancelar</button>
                    <button className="button button-primary" disabled={saving} type="submit">Salvar</button>
                  </div>
                </form>
              ) : (
                <>
                  <h2>{collection.name}</h2>
                  <p className="collection-description">{collection.description || "Sem descrição"}</p>
                  <Link className="collection-open" to={`/collections/${collection.id}`}>
                    Abrir coleção <span aria-hidden="true">→</span>
                  </Link>
                </>
              )}
            </article>
          ))}
        </section>
      )}

      {showCreate && (
        <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setShowCreate(false);
        }}>
          <section aria-labelledby="create-collection-title" aria-modal="true" className="dialog" role="dialog">
            <p className="eyebrow">NOVA PRATELEIRA</p>
            <h2 id="create-collection-title">Criar coleção</h2>
            <form className="stack-form" onSubmit={(event) => void create(event)}>
              <label htmlFor="new-collection-name">Nome da coleção</label>
              <input autoFocus id="new-collection-name" maxLength={120} name="name" required />
              <label htmlFor="new-collection-description">Descrição <span className="optional-label">opcional</span></label>
              <textarea id="new-collection-description" name="description" rows={3} />
              <div className="form-actions">
                <button className="button button-secondary" onClick={() => setShowCreate(false)} type="button">Cancelar</button>
                <button className="button button-primary" disabled={saving} type="submit">Criar coleção</button>
              </div>
            </form>
          </section>
        </div>
      )}

      {deleting && (
        <div className="dialog-backdrop">
          <section aria-labelledby="delete-collection-title" aria-modal="true" className="dialog dialog-small" role="dialog">
            <p className="eyebrow">CONFIRMAR AÇÃO</p>
            <h2 id="delete-collection-title">Excluir coleção?</h2>
            <p>“{deleting.name}” e os documentos dela serão removidos.</p>
            <div className="form-actions">
              <button className="button button-secondary" onClick={() => setDeleting(null)} type="button">Manter coleção</button>
              <button className="button button-danger" disabled={saving} onClick={() => void removeCollection()} type="button">Excluir coleção</button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthProvider";
import { AppShell } from "./components/AppShell";
import { AskPage } from "./pages/AskPage";
import { CollectionPage } from "./pages/CollectionPage";
import { DocumentDetailPage } from "./pages/DocumentDetailPage";
import { LibraryPage } from "./pages/LibraryPage";
import { LoginPage } from "./pages/LoginPage";

function SessionGate({ children }: { children: React.ReactNode }) {
  const { ready, user } = useAuth();
  if (!ready) return <p className="session-check" role="status">Verificando sua sessão…</p>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function AppRoutes() {
  const { ready, user } = useAuth();
  if (!ready) return <p className="session-check" role="status">Verificando sua sessão…</p>;

  return (
    <Routes>
      <Route
        path="/login"
        element={user ? <Navigate to="/library" replace /> : <LoginPage />}
      />
      <Route
        path="/"
        element={
          <SessionGate>
            <AppShell />
          </SessionGate>
        }
      >
        <Route index element={<Navigate to="/library" replace />} />
        <Route path="library" element={<LibraryPage />} />
        <Route path="collections/:collectionId" element={<CollectionPage />} />
        <Route path="collections/:collectionId/documents/:documentId" element={<DocumentDetailPage />} />
        <Route path="collections/:collectionId/ask" element={<AskPage />} />
      </Route>
      <Route path="*" element={<Navigate to={user ? "/library" : "/login"} replace />} />
    </Routes>
  );
}

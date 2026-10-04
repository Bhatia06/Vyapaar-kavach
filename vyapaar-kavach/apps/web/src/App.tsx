import { useEffect } from "react";
import {
  Navigate,
  Route,
  Routes,
  Link,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { setUnauthorizedHandler } from "./api";
import { AuthProvider, useAuth } from "./auth";
import { Banner } from "./components/Banner";
import Login from "./pages/Login";
import Home from "./pages/Home";
import NewClaim from "./pages/NewClaim";
import CaseDetail from "./pages/CaseDetail";
import Research from "./pages/Research";

function Shell({ children }: { children: React.ReactNode }) {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <>
      <Banner />
      <nav className="topnav">
        <Link to="/" className="brand">
          Vyapaar Kavach
        </Link>
        <Link to="/" className="nav-link">
          Payments
        </Link>
        <Link to="/research" className="nav-link">
          Research
        </Link>
        <span className="spacer" />
        {me && (
          <>
            <span className="who">
              {me.display_name} ({me.role}) · {me.environment}
            </span>
            <button
              className="btn btn-outline"
              onClick={() => {
                void logout().then(() => navigate("/login"));
              }}
            >
              Sign out
            </button>
          </>
        )}
      </nav>
      {children}
    </>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { me, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <div className="page">
        <p>
          <span className="spinner" /> Restoring session…
        </p>
      </div>
    );
  }
  if (!me) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  return <Shell>{children}</Shell>;
}

function UnauthorizedRedirect() {
  const navigate = useNavigate();
  const { setMe } = useAuth();
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setMe(null);
      navigate("/login");
    });
  }, [navigate, setMe]);
  return null;
}

export default function App() {
  return (
    <AuthProvider>
      <UnauthorizedRedirect />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <Home />
            </RequireAuth>
          }
        />
        <Route
          path="/claims/new"
          element={
            <RequireAuth>
              <NewClaim />
            </RequireAuth>
          }
        />
        <Route
          path="/cases/:id"
          element={
            <RequireAuth>
              <CaseDetail />
            </RequireAuth>
          }
        />
        <Route
          path="/research"
          element={
            <RequireAuth>
              <Research />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  );
}

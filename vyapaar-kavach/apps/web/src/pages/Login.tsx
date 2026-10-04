import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { Banner } from "../components/Banner";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { setMe } = useAuth();
  const navigate = useNavigate();

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const me = await api.login(username.trim(), password);
      setMe(me);
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Banner />
      <div className="page">
        <div className="card centered">
          <h1>Vyapaar Kavach</h1>
          <p className="muted small">
            Merchant payment exception assistant — sign in to continue.
          </p>
          {error && <div className="alert alert-error">{error}</div>}
          <form onSubmit={onSubmit}>
            <div className="field">
              <label htmlFor="username">Email</label>
              <input
                id="username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <button className="btn btn-primary" type="submit" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
          <div className="alert alert-info small" style={{ marginTop: 16 }}>
            <strong>Demo accounts</strong>
            <br />
            owner@demo / owner123
            <br />
            staff@demo / staff123
            <br />
            research@demo / research123
          </div>
        </div>
      </div>
    </>
  );
}

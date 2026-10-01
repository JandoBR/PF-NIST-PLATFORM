import { useState } from 'react';
import { ShieldCheck, Loader2, LogIn, AlertTriangle } from 'lucide-react';
import { ApiError, login } from '@/lib/api';
import type { AuthUser } from '@/lib/api';

interface LoginProps {
  onLogin: (user: AuthUser) => void;
}

export function Login({ onLogin }: LoginProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setSubmitting(true);
    setError(null);
    try {
      onLogin(await login(username.trim(), password));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'No se pudo iniciar sesión.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid-bg flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="relative flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-cyan-500/20 to-indigo-500/20 ring-1 ring-cyan-500/30">
            <ShieldCheck className="h-7 w-7 text-cyan-300" strokeWidth={2.2} />
          </div>
          <h1 className="mt-4 text-lg font-bold tracking-tight text-white">
            Plataforma de Madurez de Seguridad
          </h1>
          <p className="mt-1 text-xs text-slate-500">
            Evaluación NIST CSF 2.0 · Accede con tu cuenta
          </p>
        </div>

        <form onSubmit={handleSubmit} className="card space-y-4 p-6">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-slate-400">Usuario</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              className="input"
              placeholder="tu usuario"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-slate-400">Contraseña</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className="input"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-lg border border-rose-500/30 bg-rose-500/[0.07] p-3 text-xs text-rose-200">
              <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting || !username.trim() || !password}
            className="btn-primary w-full justify-center"
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogIn className="h-4 w-4" />}
            {submitting ? 'Entrando…' : 'Iniciar sesión'}
          </button>

          <p className="text-center text-[11px] text-slate-600">
            Demo: <span className="font-mono text-slate-400">demo</span> /{' '}
            <span className="font-mono text-slate-400">demo123</span>
          </p>
        </form>

        <p className="mt-6 text-center text-xs text-slate-700">
          Prototipo académico · No apto para uso en producción
        </p>
      </div>
    </div>
  );
}

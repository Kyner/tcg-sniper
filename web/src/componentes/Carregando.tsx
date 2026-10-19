// Indicador de carregamento (DaisyUI loading).
export function Carregando() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <span className="loading loading-spinner loading-lg" aria-label="Carregando" />
    </div>
  );
}

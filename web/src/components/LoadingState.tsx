export function LoadingState({ label }: { label: string }) {
  return (
    <p className="loading-state" role="status">
      <span className="loading-mark" aria-hidden="true" />
      {label}
    </p>
  );
}

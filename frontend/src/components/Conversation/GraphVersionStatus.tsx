import { Button } from '@/ui/button';

export type GraphVersionStatusProps = {
  graphVersion: number | null;
  activeGraphVersion: number;
  isOlder: boolean;
  onStartLatest: () => Promise<void>;
  isStartingLatest: boolean;
};

export function GraphVersionStatus({
  graphVersion,
  activeGraphVersion,
  isOlder,
  onStartLatest,
  isStartingLatest,
}: GraphVersionStatusProps) {
  if (graphVersion === null) {
    return (
      <div data-testid="graph-version-status" className="px-3 py-1.5 text-xs text-muted-foreground">
        Pinned Graph Version unavailable
      </div>
    );
  }

  return (
    <div
      data-testid="graph-version-status"
      className="flex items-center gap-2 border-b border-border bg-card px-3 py-1.5 text-xs text-muted-foreground"
    >
      <span>
        Pinned Graph Version {graphVersion}{isOlder ? `; latest is ${activeGraphVersion}` : ''}
      </span>
      {isOlder && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-6 px-2 text-xs"
          onClick={() => void onStartLatest()}
          disabled={isStartingLatest}
        >
          {isStartingLatest ? 'Starting latest…' : 'Start latest'}
        </Button>
      )}
    </div>
  );
}

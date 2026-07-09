import { useEffect, useState } from "react"
import {
  MoreHorizontal,
  Trash2,
  ArrowUpRight,
  Layers,
} from "lucide-react"
import { api, type Session } from "@/services/api"
import { ConfirmDialog } from "@/components/ConfirmDialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu"
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/ui/sidebar"

interface DeckHistoryProps {
  onSessionSelect: (sessionId: string) => void
  onNewSession?: () => void
  currentSessionId?: string | null
  refreshKey?: number
}

export function DeckHistory({
  onSessionSelect,
  onNewSession,
  currentSessionId,
  refreshKey,
}: DeckHistoryProps) {
  const { isMobile } = useSidebar()
  const [sessions, setSessions] = useState<Session[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)

  const loadSessions = () => {
    api.listSessions(5)
      .then(result => {
        setSessions(result.sessions)
        setLoadError(null)
      })
      .catch(err => {
        // Loud, like the Design System library: a failed list must never
        // render as silently empty (which reads as data loss).
        console.error('Failed to load sessions:', err)
        setLoadError(err instanceof Error ? err.message : 'Failed to load sessions')
      })
  }

  useEffect(() => {
    loadSessions()
  }, [refreshKey])

  const handleDeleteClick = (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setDeleteTarget(sessionId)
  }

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return
    const id = deleteTarget
    const wasActive = id === currentSessionId
    setDeleteTarget(null)
    try {
      await api.deleteSession(id)
      loadSessions()
      if (wasActive) onNewSession?.()
    } catch (err) {
      console.error('Failed to delete session:', err)
    }
  }

  // Match page header format: Just now, Xm ago, Xh ago, Xd ago
  const getTimeAgo = (dateStr: string) => {
    const date = new Date(dateStr)
    const seconds = Math.floor((new Date().getTime() - date.getTime()) / 1000)
    if (seconds < 60) return 'Just now'
    const minutes = Math.floor(seconds / 60)
    if (minutes < 60) return `${minutes}m ago`
    const hours = Math.floor(minutes / 60)
    if (hours < 24) return `${hours}h ago`
    const days = Math.floor(hours / 24)
    return `${days}d ago`
  }

  if (loadError) {
    return (
      <SidebarGroup className="group-data-[collapsible=icon]:hidden">
        <SidebarGroupLabel>Recent Decks</SidebarGroupLabel>
        <div
          className="mx-2 rounded-md border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive"
          role="alert"
          data-testid="deck-history-error"
        >
          Error: {loadError}
          <button
            type="button"
            onClick={loadSessions}
            className="mt-1 block rounded border border-destructive/30 bg-background px-2 py-0.5 font-medium hover:bg-destructive/10"
            data-testid="deck-history-retry"
          >
            Retry
          </button>
        </div>
      </SidebarGroup>
    )
  }

  if (sessions.length === 0) {
    return null
  }

  return (
    <SidebarGroup className="group-data-[collapsible=icon]:hidden">
      <ConfirmDialog
        open={!!deleteTarget}
        title="Delete Session"
        message="Delete this session? This cannot be undone."
        onConfirm={handleDeleteConfirm}
        onCancel={() => setDeleteTarget(null)}
      />
      <SidebarGroupLabel>Recent Decks</SidebarGroupLabel>
      <SidebarMenu>
        {sessions.map((session) => (
          <SidebarMenuItem key={session.session_id}>
            <SidebarMenuButton
              onClick={() => onSessionSelect(session.session_id)}
              title={session.title || 'Untitled'}
              isActive={session.session_id === currentSessionId}
            >
              <Layers className="size-4 shrink-0 text-sidebar-foreground/60" />
              <div className="flex min-w-0 flex-1 flex-col gap-0 leading-tight overflow-hidden">
                <span className="truncate">{session.title || 'Untitled'}</span>
                <span className="text-[10px] text-sidebar-foreground/50">
                  {(() => {
                    const count = session.slide_count ?? session.slide_deck?.slide_count ?? 0;
                    return `${count} slide${count !== 1 ? 's' : ''} · Saved ${getTimeAgo(session.last_activity || session.created_at)}`;
                  })()}
                </span>
              </div>
            </SidebarMenuButton>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuAction showOnHover>
                  <MoreHorizontal />
                  <span className="sr-only">More</span>
                </SidebarMenuAction>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                className="w-48 rounded-lg"
                side={isMobile ? "bottom" : "right"}
                align={isMobile ? "end" : "start"}
              >
                <DropdownMenuItem onClick={() => onSessionSelect(session.session_id)}>
                  <ArrowUpRight className="text-muted-foreground" />
                  <span>Open Deck</span>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={(e) => handleDeleteClick(session.session_id, e)}>
                  <Trash2 className="text-muted-foreground" />
                  <span>Delete</span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        ))}
      </SidebarMenu>
    </SidebarGroup>
  )
}

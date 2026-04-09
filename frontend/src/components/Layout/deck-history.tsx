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
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)

  useEffect(() => {
    api.listSessions(5)
      .then(result => setSessions(result.sessions))
      .catch(err => console.error('Failed to load sessions:', err))
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
      const result = await api.listSessions(5)
      setSessions(result.sessions)
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

import { useEffect, useState } from "react"
import {
  MoreHorizontal,
  Trash2,
  ArrowUpRight,
  Layers,
} from "lucide-react"
import { api, type Session } from "@/services/api"
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
  onViewAll: () => void
  currentSessionId?: string | null
}

export function DeckHistory({
  onSessionSelect,
  onViewAll,
  currentSessionId,
}: DeckHistoryProps) {
  const { isMobile } = useSidebar()
  const [sessions, setSessions] = useState<Session[]>([])

  useEffect(() => {
    // Load recent sessions (limit to 5)
    api.listSessions(5)
      .then(result => setSessions(result.sessions))
      .catch(err => console.error('Failed to load sessions:', err))
  }, [currentSessionId]) // Reload when current session changes

  const handleDelete = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('Delete this session? This cannot be undone.')) return

    try {
      await api.deleteSession(sessionId)
      // Reload sessions after delete
      const result = await api.listSessions(5)
      setSessions(result.sessions)
    } catch (err) {
      console.error('Failed to delete session:', err)
    }
  }

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    const hours = Math.floor(diff / (1000 * 60 * 60))

    if (hours < 1) return 'Just now'
    if (hours < 24) return `${hours} hour${hours > 1 ? 's' : ''} ago`
    if (hours < 48) return 'Yesterday'
    if (hours < 168) return `${Math.floor(hours / 24)} days ago`
    return 'Last week'
  }

  if (sessions.length === 0) {
    return null
  }

  return (
    <SidebarGroup className="group-data-[collapsible=icon]:hidden">
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
              <div className="flex flex-col gap-0 leading-tight">
                <span className="truncate">{session.title || 'Untitled'}</span>
                <span className="text-[10px] text-sidebar-foreground/50">
                  {session.slide_deck?.slide_count || 0} slides &middot; {formatDate(session.last_activity || session.created_at)}
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
                <DropdownMenuItem onClick={(e) => handleDelete(session.session_id, e)}>
                  <Trash2 className="text-muted-foreground" />
                  <span>Delete</span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        ))}
        <SidebarMenuItem>
          <SidebarMenuButton
            className="text-sidebar-foreground/70"
            onClick={onViewAll}
          >
            <MoreHorizontal />
            <span>View All Decks</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarGroup>
  )
}

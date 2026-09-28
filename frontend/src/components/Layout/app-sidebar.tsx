import * as React from "react"
import {
  Plus,
  User,
  HelpCircle,
  FileText,
  Palette,
  Image,
  Layers,
  Compass,
  Shapes,
  ShieldCheck,
} from "lucide-react"
import { useNavigate } from "react-router-dom"
import { NavMain } from "@/components/Layout/nav-main"
import { NavSecondary } from "@/components/Layout/nav-secondary"
import { DeckHistory } from "@/components/Layout/deck-history"
import { BrandHeader } from "@/components/Layout/brand-header"
import { useTour } from "@/contexts/TourContext"
import { useCurrentUser } from "@/hooks/useCurrentUser"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
} from "@/ui/sidebar"

type ViewMode = 'main' | 'profiles' | 'deck_prompts' | 'design_systems' | 'slide_styles' | 'images' | 'history' | 'help'

interface AppSidebarProps extends React.ComponentProps<typeof Sidebar> {
  currentView: ViewMode
  onViewChange: (view: ViewMode) => void
  onSessionSelect: (sessionId: string) => void
  onNewSession: () => void
  currentSessionId?: string | null
  sessionsRefreshKey?: number
}

const navMainItems = [
  {
    title: "New Deck",
    viewId: "main",
    icon: Plus,
  },
  {
    title: "View All Decks",
    viewId: "history",
    icon: Layers,
  },
]

const navSecondaryItems = [
  {
    title: "Agent profiles",
    viewId: "profiles",
    icon: User,
  },
  {
    title: "Deck prompts",
    viewId: "deck_prompts",
    icon: FileText,
  },
  {
    title: "Design systems",
    viewId: "design_systems",
    icon: Shapes,
  },
  {
    title: "Slide styles",
    viewId: "slide_styles",
    icon: Palette,
  },
  {
    title: "Images",
    viewId: "images",
    icon: Image,
  },
  {
    title: "Help",
    viewId: "help",
    icon: HelpCircle,
  },
]

export function AppSidebar({
  currentView,
  onViewChange,
  onSessionSelect,
  onNewSession,
  currentSessionId,
  sessionsRefreshKey,
  ...props
}: AppSidebarProps) {
  const { startTour } = useTour()
  const navigate = useNavigate()
  // UX only: /admin enforces its own gate and every admin API route checks server-side.
  const { isAdmin, loading } = useCurrentUser()
  const configureItems = !loading && isAdmin
    ? [...navSecondaryItems, { title: "Admin", viewId: "admin", icon: ShieldCheck }]
    : navSecondaryItems

  return (
    <Sidebar className="border-r-0" data-tour="sidebar" {...props}>
      <SidebarHeader>
        <BrandHeader />
        <div data-tour="new-deck">
          <NavMain
            items={navMainItems}
            activeView={currentView}
            onNavigate={(viewId) => {
              if (viewId === 'main') {
                onNewSession()
              } else {
                onViewChange(viewId as ViewMode)
              }
            }}
          />
        </div>
      </SidebarHeader>
      <SidebarContent data-tour="deck-history">
        <DeckHistory
          onSessionSelect={onSessionSelect}
          onNewSession={onNewSession}
          currentSessionId={currentSessionId}
          refreshKey={sessionsRefreshKey}
        />
      </SidebarContent>
      <SidebarFooter>
        <SidebarGroup data-tour="configure-section">
          <SidebarGroupLabel>Configure</SidebarGroupLabel>
          <NavSecondary
            items={configureItems}
            activeView={currentView}
            onNavigate={(viewId) => {
              if (viewId === 'admin') {
                navigate('/admin')
              } else {
                onViewChange(viewId as ViewMode)
              }
            }}
          />
        </SidebarGroup>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton onClick={startTour}>
              <Compass />
              <span>App Tour</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}

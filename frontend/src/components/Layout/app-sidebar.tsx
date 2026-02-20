import * as React from "react"
import {
  Plus,
  User,
  HelpCircle,
  FileText,
  Palette,
  Image,
} from "lucide-react"
import { NavMain } from "@/components/Layout/nav-main"
import { NavSecondary } from "@/components/Layout/nav-secondary"
import { DeckHistory } from "@/components/Layout/deck-history"
import { BrandHeader } from "@/components/Layout/brand-header"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
  SidebarGroup,
  SidebarGroupLabel,
} from "@/ui/sidebar"

type ViewMode = 'main' | 'profiles' | 'deck_prompts' | 'slide_styles' | 'images' | 'history' | 'help'

interface AppSidebarProps extends React.ComponentProps<typeof Sidebar> {
  currentView: ViewMode
  onViewChange: (view: ViewMode) => void
  onSessionSelect: (sessionId: string) => void
  onNewSession: () => void
  currentSessionId?: string | null
  profileName?: string
  sessionsRefreshKey?: number
}

const navMainItems = [
  {
    title: "New Deck",
    viewId: "main",
    icon: Plus,
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
  profileName,
  sessionsRefreshKey,
  ...props
}: AppSidebarProps) {
  return (
    <Sidebar className="border-r-0" {...props}>
      <SidebarHeader>
        <BrandHeader />
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
      </SidebarHeader>
      <SidebarContent>
        <DeckHistory
          onSessionSelect={onSessionSelect}
          onViewAll={() => onViewChange('history')}
          currentSessionId={currentSessionId}
          refreshKey={sessionsRefreshKey}
        />
      </SidebarContent>
      <SidebarFooter>
        <SidebarGroup>
          <SidebarGroupLabel>Configure</SidebarGroupLabel>
          <NavSecondary
            items={navSecondaryItems}
            activeView={currentView}
            onNavigate={(viewId) => onViewChange(viewId as ViewMode)}
          />
        </SidebarGroup>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}

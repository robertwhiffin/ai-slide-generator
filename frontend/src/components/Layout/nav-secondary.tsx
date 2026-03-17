import { type LucideIcon } from "lucide-react"
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/ui/sidebar"

export function NavSecondary({
  items,
  activeView,
  onNavigate,
}: {
  items: {
    title: string
    viewId: string
    icon: LucideIcon
  }[]
  activeView?: string
  onNavigate: (viewId: string) => void
}) {
  return (
    <SidebarGroup>
      <SidebarGroupContent>
        <SidebarMenu>
          {items.map((item) => (
            <SidebarMenuItem key={item.title}>
              <SidebarMenuButton
                isActive={activeView === item.viewId}
                onClick={() => onNavigate(item.viewId)}
              >
                <item.icon />
                <span>{item.title}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}

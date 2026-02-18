import { Save, Download, Play } from "lucide-react"
import { Button } from "@/ui/button"
import { SidebarTrigger } from "@/ui/sidebar"
import { Separator } from "@/ui/separator"

interface PageHeaderProps {
  title: string
  subtitle?: string
  onSave?: () => void
  onExport?: () => void
  onPresent?: () => void
  profileSelector?: React.ReactNode
  isGenerating?: boolean
}

export function PageHeader({
  title,
  subtitle,
  onSave,
  onExport,
  onPresent,
  profileSelector,
  isGenerating = false,
}: PageHeaderProps) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-border bg-card px-4">
      {/* Sidebar Toggle */}
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="h-4" />

      {/* Left: Title */}
      <div className="flex flex-1 items-center">
        <div className="flex flex-col">
          <h1 className="text-sm font-medium text-foreground">{title}</h1>
          {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
        </div>
      </div>

      {/* Right: Actions and Profile */}
      <div className="flex items-center gap-2">
        {onSave && (
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={onSave}
            disabled={isGenerating}
          >
            <Save className="size-3.5" />
            Save
          </Button>
        )}
        {onExport && (
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={onExport}
            disabled={isGenerating}
          >
            <Download className="size-3.5" />
            Export
          </Button>
        )}
        {onPresent && (
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={onPresent}
            disabled={isGenerating}
          >
            <Play className="size-3.5" />
            Present
          </Button>
        )}

        {profileSelector && (
          <>
            <div className="mx-2 h-5 w-px bg-border" />
            {profileSelector}
          </>
        )}
      </div>
    </header>
  )
}
